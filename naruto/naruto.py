import discord
from discord.ext import commands
import aiohttp
from bs4 import BeautifulSoup
import asyncio
import io
import re
import logging
import time
import random
import json
import os
import pickle
import base64
import redis.asyncio as redis
from typing import Optional, Dict, List, Tuple, Any, Union
from datetime import datetime, timedelta
from collections import deque

# Set up logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)

class Narutodle(commands.Cog):
    """A cog for interacting with Narutodle.net using Redis for storage"""
    
    def __init__(self, bot, redis_url=None):
        self.bot = bot
        self.base_url = "https://narutodle.net"
        self.session = None  # Will be initialized in cog_load
        self.modes = ["classic", "jutsu", "quote", "eye"]
        
        # Redis connection
        self.redis_url = redis_url or os.getenv("REDIS_URL", "redis://localhost:6379/0")
        self.redis = None  # Will be initialized in cog_load
        
        # Cache expiry (defaults to 24 hours)
        self.cache_ttl = 86400
        
        # Logger for this cog
        self.logger = logging.getLogger('narutodle_cog')
        
        # Rate limiting settings
        self.request_timestamps = deque(maxlen=10)  # Store timestamps of last 10 requests
        self.min_request_interval = 1.0  # Minimum time between requests (seconds)
        self.rate_limit = 10  # Max requests per rate_limit_period
        self.rate_limit_period = 60  # Period in seconds for rate limit (e.g., 10 req/60 sec)
        self.rate_limit_lock = asyncio.Lock()  # Lock for rate limiting
        
        # Dictionary to track active guessing games
        self.active_games = {}
        
    async def cog_load(self):
        """Initialize the aiohttp session and redis connection when the cog is loaded."""
        self.session = aiohttp.ClientSession()
        self.logger.info("Narutodle cog loaded and session initialized")
        
        # Initialize Redis connection
        try:
            self.redis = await redis.from_url(self.redis_url)
            # Test connection
            await self.redis.ping()
            self.logger.info(f"Successfully connected to Redis at {self.redis_url}")
        except Exception as e:
            self.logger.error(f"Failed to connect to Redis: {e}")
            self.logger.warning("Falling back to in-memory cache")
            self.redis = None
        
    async def cog_unload(self):
        """Close the aiohttp session and redis connection when the cog is unloaded."""
        if self.session and not self.session.closed:
            await self.session.close()
            self.logger.info("Closed aiohttp session on cog unload")
            
        if self.redis:
            await self.redis.close()
            self.logger.info("Closed Redis connection on cog unload")
            
    async def _apply_rate_limit(self):
        """Apply rate limiting to avoid overloading the website."""
        async with self.rate_limit_lock:
            current_time = time.time()
            
            # Clean up old timestamps
            while self.request_timestamps and current_time - self.request_timestamps[0] > self.rate_limit_period:
                self.request_timestamps.popleft()
                
            # Check if we've hit the rate limit
            if len(self.request_timestamps) >= self.rate_limit:
                oldest_request = self.request_timestamps[0]
                time_to_wait = self.rate_limit_period - (current_time - oldest_request) + 0.1
                
                if time_to_wait > 0:
                    self.logger.warning(f"Rate limit hit, waiting {time_to_wait:.2f} seconds")
                    await asyncio.sleep(time_to_wait)
            
            # Check if we need to wait between requests
            if self.request_timestamps and current_time - self.request_timestamps[-1] < self.min_request_interval:
                wait_time = self.min_request_interval - (current_time - self.request_timestamps[-1])
                # Add a small random delay to prevent obvious patterns
                wait_time += random.uniform(0.1, 0.5)
                await asyncio.sleep(wait_time)
                
            # Add current time to timestamps
            self.request_timestamps.append(time.time())
    
    async def get_page_content(self, url: str) -> Optional[str]:
        """Get the HTML content of a page with error handling and rate limiting."""
        try:
            # Apply rate limiting
            await self._apply_rate_limit()
            
            # Use custom headers with rotating user agents to avoid being blocked
            user_agents = [
                'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/93.0.4577.82 Safari/537.36',
                'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/15.0 Safari/605.1.15',
                'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/94.0.4606.81 Safari/537.36',
                'Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:93.0) Gecko/20100101 Firefox/93.0'
            ]
            
            headers = {
                'User-Agent': random.choice(user_agents),
                'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
                'Accept-Language': 'en-US,en;q=0.5',
                'Connection': 'keep-alive',
                'Upgrade-Insecure-Requests': '1',
                'Cache-Control': 'max-age=0',
                'Referer': self.base_url
            }
            
            async with self.session.get(url, headers=headers, timeout=10) as response:
                if response.status != 200:
                    self.logger.warning(f"Failed to fetch {url}: HTTP {response.status}")
                    return None
                    
                self.logger.info(f"Successfully fetched {url}")
                return await response.text()
                
        except asyncio.TimeoutError:
            self.logger.error(f"Timeout while fetching {url}")
            return None
        except Exception as e:
            self.logger.error(f"Error fetching {url}: {e}")
            return None
            
    async def get_image(self, url: str, force_refresh: bool = False) -> Optional[io.BytesIO]:
        """Get an image from a URL and return it as a bytes object."""
        if not url:
            self.logger.warning("No image URL provided")
            return None
            
        # Fix relative URLs
        if url.startswith('/'):
            url = f"{self.base_url}{url}"
        elif not url.startswith(('http://', 'https://')):
            url = f"{self.base_url}/{url}"
            
        self.logger.info(f"Fetching image from: {url}")
            
        # Generate a unique cache key for the image
        url_hash = str(hash(url))
        cache_key = f"image:{url_hash}"
            
        # Check Redis cache first
        if not force_refresh and self.redis:
            try:
                cached_image = await self.redis.get(cache_key)
                if cached_image:
                    self.logger.info(f"Using cached image for {url}")
                    # Convert the cached bytes to BytesIO
                    try:
                        image_io = io.BytesIO(cached_image)
                        image_io.seek(0)
                        
                        # Verify image integrity
                        test_read = image_io.read(1)
                        if not test_read:
                            # Corrupted cache, will fetch again
                            self.logger.warning(f"Corrupted cached image for {url}")
                            await self.redis.delete(cache_key)
                        else:
                            # Reset the position and return
                            image_io.seek(0)
                            return image_io
                    except Exception as e:
                        self.logger.error(f"Error reading cached image: {e}")
                        await self.redis.delete(cache_key)
            except Exception as e:
                self.logger.error(f"Redis error while getting image: {e}")
        
        # Apply rate limiting
        await self._apply_rate_limit()
        
        # Custom headers for image request    
        headers = {
            'User-Agent': random.choice([
                'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/93.0.4577.82 Safari/537.36',
                'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/15.0 Safari/605.1.15',
                'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/94.0.4606.81 Safari/537.36'
            ]),
            'Accept': 'image/webp,image/apng,image/*,*/*;q=0.8',
            'Accept-Language': 'en-US,en;q=0.5',
            'Referer': self.base_url
        }
            
        try:
            async with self.session.get(url, headers=headers, timeout=10) as response:
                if response.status != 200:
                    self.logger.warning(f"Failed to fetch image {url}: HTTP {response.status}")
                    return None
                    
                image_data = await response.read()
                image_io = io.BytesIO(image_data)
                image_io.seek(0)
                
                # Cache the image in Redis if available
                if self.redis:
                    try:
                        await self.redis.set(cache_key, image_data)
                        await self.redis.expire(cache_key, self.cache_ttl)
                        self.logger.info(f"Successfully cached image from {url} in Redis")
                    except Exception as e:
                        self.logger.error(f"Redis error while caching image: {e}")
                
                return image_io
                
        except asyncio.TimeoutError:
            self.logger.error(f"Timeout while fetching image {url}")
            return None
        except Exception as e:
            self.logger.error(f"Error fetching image {url}: {e}")
            return None
            
    async def get_current_narutodle(self, mode: str = "classic", refresh: bool = False) -> Dict:
        """Get the current Narutodle character for the specified mode.
        
        Args:
            mode: The game mode to fetch ("classic", "jutsu", "quote", or "eye")
            refresh: Force refresh the cache for this request
        """
        mode = mode.lower()
        if mode not in self.modes:
            return {"error": f"Invalid mode. Choose from: {', '.join(self.modes)}"}
        
        # Check if we should use the Redis cache
        cache_key = f"narutodle:{mode}"
        if not refresh and self.redis:
            try:
                cached_data = await self.redis.get(cache_key)
                if cached_data:
                    self.logger.info(f"Using cached data for {mode} mode from Redis")
                    return json.loads(cached_data)
            except Exception as e:
                self.logger.error(f"Redis error while getting data: {e}")
            
        # Track parsing attempts for fallback strategies
        parsing_methods = [
            self._parse_primary_method,
            self._parse_fallback_method,
            self._parse_last_resort_method
        ]
        
        # Try each parsing method until one works
        for parse_method in parsing_methods:
            try:
                result = await parse_method(mode)
                if result and not result.get("error"):
                    # Cache successful results in Redis if available
                    if self.redis:
                        try:
                            # For results with image_url, we store the image separately
                            if result.get("image_url"):
                                # We've already cached the image via get_image
                                pass
                                
                            # Store the result as JSON in Redis
                            await self.redis.set(cache_key, json.dumps(result))
                            await self.redis.expire(cache_key, self.cache_ttl)
                        except Exception as e:
                            self.logger.error(f"Redis error while caching data: {e}")
                    
                    return result
            except Exception as e:
                self.logger.warning(f"Parsing method {parse_method.__name__} failed for {mode}: {e}")
                continue
                
        # If all parsing methods fail, return error
        return {"error": f"Failed to parse {mode} data from Narutodle. Site structure may have changed."}
        
    async def _parse_primary_method(self, mode: str) -> Dict:
        """Primary parsing method using specific CSS selectors.
        
        This is the main strategy that relies on the expected HTML structure.
        """
        url = f"{self.base_url}/{mode}"
        html = await self.get_page_content(url)
        if not html:
            return {"error": f"Failed to load {mode} mode from Narutodle."}
        
        soup = BeautifulSoup(html, 'html.parser')
        
        result = {
            "mode": mode,
            "timestamp": datetime.utcnow().isoformat(),
            "image_url": None,
            "clue": None,
            "data": {}
        }
        
        # Extract the main game container
        game_container = soup.select_one("div.game-container")
        if not game_container:
            self.logger.warning(f"Could not find game-container in {mode} mode")
            return {"error": f"Failed to parse {mode} mode from Narutodle."}
        
        # Different extraction logic based on the mode
        if mode == "classic":
            # Extract character properties from the classic mode
            properties = soup.select("div.properties-container div.property")
            for prop in properties:
                prop_name = prop.select_one("div.property-name")
                prop_value = prop.select_one("div.property-value")
                if prop_name and prop_value:
                    result["data"][prop_name.text.strip()] = prop_value.text.strip()
        
        elif mode == "jutsu":
            # Extract jutsu GIF/image
            jutsu_img = soup.select_one("div.jutsu-container img")
            if jutsu_img and jutsu_img.has_attr('src'):
                img_src = jutsu_img['src']
                if not img_src.startswith(('http://', 'https://')):
                    img_src = f"{self.base_url}/{img_src.lstrip('/')}"
                result["image_url"] = img_src
                
                # Pre-fetch and cache the image
                await self.get_image(img_src)
        
        elif mode == "quote":
            # Extract quote text
            quote_element = soup.select_one("div.quote-container")
            if quote_element:
                result["clue"] = quote_element.text.strip()
                
                # Extract recipient and arc if available
                info_elements = soup.select("div.quote-info div")
                for info in info_elements:
                    if "Recipient:" in info.text:
                        result["data"]["recipient"] = info.text.replace("Recipient:", "").strip()
                    elif "Arc:" in info.text:
                        result["data"]["arc"] = info.text.replace("Arc:", "").strip()
        
        elif mode == "eye":
            # Extract eye image
            eye_img = soup.select_one("div.eye-container img")
            if eye_img and eye_img.has_attr('src'):
                img_src = eye_img['src']
                if not img_src.startswith(('http://', 'https://')):
                    img_src = f"{self.base_url}/{img_src.lstrip('/')}"
                result["image_url"] = img_src
                
                # Pre-fetch and cache the image
                await self.get_image(img_src)
        
        # Check if we got meaningful data
        if (mode == "classic" and not result["data"]) or \
           (mode == "jutsu" and not result["image_url"]) or \
           (mode == "quote" and not result["clue"]) or \
           (mode == "eye" and not result["image_url"]):
            self.logger.warning(f"Primary method found container but couldn't extract data for {mode}")
            return {"error": "Failed to extract data"}
            
        return result
        
    async def _parse_fallback_method(self, mode: str) -> Dict:
        """Fallback parsing method using more generic selectors.
        
        This method tries to find the content using broader selectors if the specific ones fail.
        """
        url = f"{self.base_url}/{mode}"
        html = await self.get_page_content(url)
        if not html:
            return {"error": f"Failed to load {mode} mode from Narutodle."}
        
        soup = BeautifulSoup(html, 'html.parser')
        
        result = {
            "mode": mode,
            "timestamp": datetime.utcnow().isoformat(),
            "image_url": None,
            "clue": None,
            "data": {}
        }
        
        # Look for content with more generic selectors and pattern matching
        if mode == "classic":
            # Try to find any table-like structure or div pairs
            property_pairs = []
            
            # Try to find properties within any div that contains both name and value patterns
            for div in soup.select('div'):
                children = list(div.find_all(['div', 'span', 'p'], recursive=False))
                if len(children) == 2:
                    name_text = children[0].get_text().strip()
                    value_text = children[1].get_text().strip()
                    if name_text and value_text and len(name_text) < 20:  # Likely a property name
                        property_pairs.append((name_text, value_text))
            
            # Process the found properties
            for name, value in property_pairs:
                result["data"][name] = value
                
        elif mode == "jutsu":
            # Try to find any image in the page
            for img in soup.find_all('img'):
                src = img.get('src', '')
                if 'jutsu' in src.lower() or any(ext in src.lower() for ext in ['.gif', '.jpg', '.png']):
                    if not src.startswith(('http://', 'https://')):
                        src = f"{self.base_url}/{src.lstrip('/')}"
                    result["image_url"] = src
                    
                    # Pre-fetch and cache the image
                    await self.get_image(src)
                    break
                    
        elif mode == "quote":
            # Try to find quote text - look for blockquote or div with significant text
            quote_candidates = []
            
            # Check for blockquotes
            for blockquote in soup.find_all('blockquote'):
                quote_candidates.append(blockquote.get_text().strip())
                
            # Check for divs with quotes or paragraphs that look like quotes
            for div in soup.find_all(['div', 'p']):
                text = div.get_text().strip()
                # Identify potential quotes by quote marks or length and punctuation
                if (text.startswith('"') and text.endswith('"')) or \
                   (len(text) > 40 and len(text) < 400 and text.endswith(('!', '.', '?', '"'))):
                    quote_candidates.append(text)
            
            # Select the most likely quote
            if quote_candidates:
                result["clue"] = max(quote_candidates, key=len)
                
            # Try to find associated metadata (recipient, arc)
            for div in soup.find_all(['div', 'span', 'p']):
                text = div.get_text().strip()
                if "recipient" in text.lower() or "said to" in text.lower():
                    result["data"]["recipient"] = text.replace("Recipient:", "").strip()
                elif "arc" in text.lower() or "episode" in text.lower():
                    result["data"]["arc"] = text.replace("Arc:", "").strip()
                    
        elif mode == "eye":
            # Try to find eye images
            for img in soup.find_all('img'):
                src = img.get('src', '')
                if 'eye' in src.lower() or any(term in src.lower() for term in ['sharingan', 'byakugan', 'rinnegan']):
                    if not src.startswith(('http://', 'https://')):
                        src = f"{self.base_url}/{src.lstrip('/')}"
                    result["image_url"] = src
                    
                    # Pre-fetch and cache the image
                    await self.get_image(src)
                    break
                    
        # Check if we got any meaningful data
        if (mode == "classic" and result["data"]) or \
           (mode == "jutsu" and result["image_url"]) or \
           (mode == "quote" and result["clue"]) or \
           (mode == "eye" and result["image_url"]):
            return result
        else:
            return {"error": "Fallback method failed to extract meaningful data"}
            
    async def _parse_last_resort_method(self, mode: str) -> Dict:
        """Last resort method using regex and minimal assumptions about the page structure."""
        url = f"{self.base_url}/{mode}"
        html = await self.get_page_content(url)
        if not html:
            return {"error": f"Failed to load {mode} mode from Narutodle."}
            
        result = {
            "mode": mode,
            "timestamp": datetime.utcnow().isoformat(),
            "image_url": None,
            "clue": None,
            "data": {}
        }
        
        # Extract information using regex patterns
        if mode == "classic":
            # Look for property patterns with regex
            property_pattern = r'<div[^>]*>([\w\s]+)[:<].*?<div[^>]*>([\w\s-]+)</div>'
            properties = re.findall(property_pattern, html)
            for name, value in properties:
                name = name.strip()
                value = value.strip()
                if name and value:
                    result["data"][name] = value
                    
        elif mode in ["jutsu", "eye"]:
            # Find any image URL
            img_pattern = r'<img[^>]*src=["\'](\/[^"\']+)["\']'
            img_matches = re.findall(img_pattern, html)
            
            if img_matches:
                # Get the first image
                img_src = img_matches[0]
                if not img_src.startswith(('http://', 'https://')):
                    img_src = f"{self.base_url}{img_src}"
                result["image_url"] = img_src
                
                # Pre-fetch and cache the image
                await self.get_image(img_src)
                
        elif mode == "quote":
            # Find potential quotes
            quote_pattern = r'<div[^>]*quote[^>]*>(.*?)</div>'
            quote_matches = re.findall(quote_pattern, html, re.DOTALL)
            
            if quote_matches:
                # Use the first quote found
                quote_text = re.sub(r'<[^>]+>', ' ', quote_matches[0])
                quote_text = re.sub(r'\s+', ' ', quote_text).strip()
                result["clue"] = quote_text
                
        # Check if we got any meaningful data
        if (mode == "classic" and result["data"]) or \
           (mode == "jutsu" and result["image_url"]) or \
           (mode == "quote" and result["clue"]) or \
           (mode == "eye" and result["image_url"]):
            return result
        else:
            return {"error": "Last resort method failed to extract meaningful data"}
            
    def _check_permissions(self, ctx, admin_only=False):
        """Check if a user has the appropriate permissions to run a command.
        
        Args:
            ctx: Command context
            admin_only: Whether the command requires admin permissions
            
        Returns:
            bool: True if the user has permission, False otherwise
        """
        # Bot owner always has permission
        if ctx.author.id == self.bot.owner_id:
            return True
            
        if admin_only:
            # Check for administrator permission
            if ctx.author.guild_permissions.administrator:
                return True
            # Check for manage_guild permission
            if ctx.author.guild_permissions.manage_guild:
                return True
            # Check for "Narutodle Admin" role
            admin_role = discord.utils.get(ctx.guild.roles, name="Narutodle Admin")
            if admin_role and admin_role in ctx.author.roles:
                return True
            return False
            
        # For regular commands, check for basic permissions
        if ctx.author.guild_permissions.manage_messages:
            return True
            
        # Check for a specific role if defined
        narutodle_role = discord.utils.get(ctx.guild.roles, name="Narutodle")
        if narutodle_role and narutodle_role in ctx.author.roles:
            return True
            
        # Default permission check - available to most users
        return True
        
    async def _check_already_played(self, user_id, guild_id, mode):
        """Check if a user has already played a specific mode today.
        
        Args:
            user_id: Discord user ID
            guild_id: Discord server ID
            mode: Game mode
            
        Returns:
            bool: True if the user has already played, False otherwise
        """
        if not self.redis:
            return False  # Can't check without Redis
            
        today = datetime.utcnow().strftime('%Y-%m-%d')
        played_key = f"played:{guild_id}:{user_id}:{mode}:{today}"
        
        try:
            result = await self.redis.exists(played_key)
            return bool(result)
        except Exception as e:
            self.logger.error(f"Redis error checking if user already played: {e}")
            return False
            
    async def _record_user_answer(self, user_id, guild_id, mode, correct, attempts):
        """Record a user's answer in Redis.
        
        Args:
            user_id: Discord user ID
            guild_id: Discord server ID
            mode: Game mode (classic, jutsu, quote, eye)
            correct: Whether the answer was correct (1 for yes, 0 for no)
            attempts: Number of attempts taken
        """
        if not self.redis:
            self.logger.warning("Cannot record user answer: Redis not available")
            return
            
        try:
            # Get current date in YYYY-MM-DD format
            today = datetime.utcnow().strftime('%Y-%m-%d')
            timestamp = datetime.utcnow().isoformat()
            
            # Mark that this user has played today
            played_key = f"played:{guild_id}:{user_id}:{mode}:{today}"
            await self.redis.set(played_key, 1)
            await self.redis.expire(played_key, 86400)  # Expire after 24 hours
            
            # Record stats for this user
            user_stats_key = f"stats:{guild_id}:{user_id}"
            
            # Increment total games counter
            await self.redis.hincrby(user_stats_key, "total_games", 1)
            
            # Increment correct answers counter if applicable
            if correct:
                await self.redis.hincrby(user_stats_key, "correct_answers", 1)
                
            # Increment mode-specific counters
            await self.redis.hincrby(user_stats_key, f"{mode}_games", 1)
            if correct:
                await self.redis.hincrby(user_stats_key, f"{mode}_correct", 1)
                
            # Update attempts for average calculation
            # We store the sum of attempts and count of games for later division
            await self.redis.hincrby(user_stats_key, "total_attempts", attempts)
            await self.redis.hincrby(user_stats_key, f"{mode}_attempts", attempts)
            
            # Store in overall leaderboard sorted sets
            leaderboard_key = f"leaderboard:{guild_id}"
            await self.redis.zincrby(leaderboard_key, 1 if correct else 0, user_id)
            
            # Store in mode-specific leaderboard sorted sets
            mode_leaderboard_key = f"leaderboard:{guild_id}:{mode}"
            await self.redis.zincrby(mode_leaderboard_key, 1 if correct else 0, user_id)
            
            # Keep a log of all answers (optional for detailed history)
            answer_log_key = f"answer_log:{guild_id}:{user_id}"
            log_entry = json.dumps({
                "mode": mode,
                "date": today,
                "correct": correct,
                "attempts": attempts,
                "timestamp": timestamp
            })
            await self.redis.lpush(answer_log_key, log_entry)
            await self.redis.ltrim(answer_log_key, 0, 99)  # Keep only last 100 entries
            
        except Exception as e:
            self.logger.error(f"Redis error recording user answer: {e}")
            
    async def _record_daily_character(self, mode, character_name):
        """Record the daily character for a specific mode in Redis."""
        if not self.redis:
            self.logger.warning("Cannot record daily character: Redis not available")
            return
            
        try:
            # Get current date in YYYY-MM-DD format
            today = datetime.utcnow().strftime('%Y-%m-%d')
            
            # Store the character for today
            daily_key = f"daily:{mode}:{today}"
            await self.redis.set(daily_key, character_name)
            await self.redis.expire(daily_key, 86400 * 7)  # Keep for a week
            
            # Add to character set
            await self.redis.sadd("narutodle:characters", character_name)
            
        except Exception as e:
            self.logger.error(f"Redis error recording daily character: {e}")
            
    async def _get_user_stats(self, user_id, guild_id=None):
        """Get statistics for a specific user from Redis.
        
        Args:
            user_id: Discord user ID
            guild_id: Discord server ID (required for Redis implementation)
            
        Returns:
            dict: Dictionary with user statistics
        """
        if not self.redis or not guild_id:
            return {
                "total_games": 0,
                "total_correct": 0,
                "average_attempts": 0,
                "modes": {}
            }
            
        try:
            stats = {
                "total_games": 0,
                "total_correct": 0,
                "average_attempts": 0,
                "modes": {}
            }
            
            # Get user stats from Redis
            user_stats_key = f"stats:{guild_id}:{user_id}"
            all_stats = await self.redis.hgetall(user_stats_key)
            
            if not all_stats:
                return stats
            
            # Convert Redis response to proper format
            # Redis returns bytes, convert to proper types
            redis_stats = {k.decode('utf-8'): int(v) for k, v in all_stats.items()}
            
            # Calculate overall stats
            stats["total_games"] = redis_stats.get("total_games", 0)
            stats["total_correct"] = redis_stats.get("correct_answers", 0)
            
            if stats["total_games"] > 0 and "total_attempts" in redis_stats:
                stats["average_attempts"] = round(redis_stats["total_attempts"] / stats["total_games"], 2)
            
            # Calculate per-mode stats
            for mode in self.modes:
                games = redis_stats.get(f"{mode}_games", 0)
                correct = redis_stats.get(f"{mode}_correct", 0)
                attempts = redis_stats.get(f"{mode}_attempts", 0)
                
                if games > 0:
                    stats["modes"][mode] = {
                        "games": games,
                        "correct": correct,
                        "average_attempts": round(attempts / games, 2) if games > 0 else 0
                    }
                else:
                    stats["modes"][mode] = {
                        "games": 0,
                        "correct": 0,
                        "average_attempts": 0
                    }
            
            return stats
            
        except Exception as e:
            self.logger.error(f"Redis error getting user stats: {e}")
            return {
                "total_games": 0,
                "total_correct": 0,
                "average_attempts": 0,
                "modes": {}
            }
            
    async def _get_leaderboard(self, guild_id, mode=None, limit=10):
        """Get the leaderboard for a specific guild from Redis.
        
        Args:
            guild_id: Discord server ID
            mode: Optional game mode to filter by
            limit: Number of users to include in the leaderboard
            
        Returns:
            list: List of dictionaries containing user stats
        """
        if not self.redis:
            return []
            
        try:
            # Determine which sorted set to use
            if mode:
                leaderboard_key = f"leaderboard:{guild_id}:{mode}"
            else:
                leaderboard_key = f"leaderboard:{guild_id}"
                
            # Get top users from the sorted set (highest scores first)
            top_users = await self.redis.zrevrange(
                leaderboard_key, 
                0, 
                limit - 1, 
                withscores=True
            )
            
            if not top_users:
                return []
                
            leaderboard = []
            for user_bytes, score in top_users:
                user_id = int(user_bytes.decode('utf-8'))
                
                # Get detailed stats for this user
                user_stats = await self._get_user_stats(user_id, guild_id)
                
                # Skip users with no games (shouldn't happen, but just in case)
                if user_stats["total_games"] == 0:
                    continue
                    
                # Get username from Discord (or use ID if not found)
                try:
                    user = self.bot.get_user(user_id)
                    username = user.name if user else f"User {user_id}"
                except:
                    username = f"User {user_id}"
                    
                # If we're looking at a specific mode, get mode-specific stats
                if mode and mode in user_stats["modes"]:
                    mode_stats = user_stats["modes"][mode]
                    leaderboard.append({
                        "user_id": user_id,
                        "username": username,
                        "games": mode_stats["games"],
                        "correct": mode_stats["correct"],
                        "accuracy": round(mode_stats["correct"] / mode_stats["games"] * 100 if mode_stats["games"] > 0 else 0, 1),
                        "avg_attempts": mode_stats["average_attempts"]
                    })
                else:
                    # Overall stats
                    leaderboard.append({
                        "user_id": user_id,
                        "username": username,
                        "games": user_stats["total_games"],
                        "correct": user_stats["total_correct"],
                        "accuracy": round(user_stats["total_correct"] / user_stats["total_games"] * 100 if user_stats["total_games"] > 0 else 0, 1),
                        "avg_attempts": user_stats["average_attempts"]
                    })
                    
            return leaderboard
            
        except Exception as e:
            self.logger.error(f"Redis error getting leaderboard: {e}")
            return []
            
    @commands.group(name="narutodle", invoke_without_command=True)
    async def narutodle(self, ctx):
        """Commands for interacting with Narutodle."""
        await ctx.send("Use one of the subcommands: classic, jutsu, quote, eye, play, stats, leaderboard, or help for more information.")
    
    @narutodle.command(name="classic")
    async def narutodle_classic(self, ctx, refresh: bool = False):
        """Get today's classic Narutodle challenge.
        
        Args:
            refresh: Optional parameter to force refresh the data
        """
        await ctx.typing()
        
        result = await self.get_current_narutodle("classic", refresh)
        if "error" in result:
            await ctx.send(f"Error: {result['error']}")
            return
        
        embed = discord.Embed(
            title="Today's Narutodle Classic Challenge",
            description="Try to guess the Naruto character based on these attributes:",
            color=discord.Color.orange(),
            url=f"{self.base_url}/classic"
        )
        
        # Add properties to the embed
        for prop_name, prop_value in result["data"].items():
            embed.add_field(name=prop_name, value=prop_value, inline=True)
        
        embed.set_footer(text=f"Data retrieved at {result['timestamp']}")
        await ctx.send(embed=embed)
    
    @narutodle.command(name="jutsu")
    async def narutodle_jutsu(self, ctx, refresh: bool = False):
        """Get today's jutsu Narutodle challenge.
        
        Args:
            refresh: Optional parameter to force refresh the data
        """
        await ctx.typing()
        
        result = await self.get_current_narutodle("jutsu", refresh)
        if "error" in result:
            await ctx.send(f"Error: {result['error']}")
            return
        
        embed = discord.Embed(
            title="Today's Narutodle Jutsu Challenge",
            description="Try to guess the character based on their jutsu:",
            color=discord.Color.blue(),
            url=f"{self.base_url}/jutsu"
        )
        
        if result["image_url"]:
            embed.set_image(url=result["image_url"])
        
        embed.set_footer(text=f"Data retrieved at {result['timestamp']}")
        await ctx.send(embed=embed)
    
    @narutodle.command(name="quote")
    async def narutodle_quote(self, ctx, refresh: bool = False):
        """Get today's quote Narutodle challenge.
        
        Args:
            refresh: Optional parameter to force refresh the data
        """
        await ctx.typing()
        
        result = await self.get_current_narutodle("quote", refresh)
        if "error" in result:
            await ctx.send(f"Error: {result['error']}")
            return
        
        embed = discord.Embed(
            title="Today's Narutodle Quote Challenge",
            description="Try to guess who said this quote:",
            color=discord.Color.green(),
            url=f"{self.base_url}/quote"
        )
        
        if result["clue"]:
            embed.add_field(name="Quote", value=result["clue"], inline=False)
        
        # Add additional info if available
        if "recipient" in result["data"]:
            embed.add_field(name="Said to", value=result["data"]["recipient"], inline=True)
        
        if "arc" in result["data"]:
            embed.add_field(name="Arc", value=result["data"]["arc"], inline=True)
        
        embed.set_footer(text=f"Data retrieved at {result['timestamp']}")
        await ctx.send(embed=embed)
    
    @narutodle.command(name="eye")
    async def narutodle_eye(self, ctx, refresh: bool = False):
        """Get today's eye Narutodle challenge.
        
        Args:
            refresh: Optional parameter to force refresh the data
        """
        await ctx.typing()
        
        result = await self.get_current_narutodle("eye", refresh)
        if "error" in result:
            await ctx.send(f"Error: {result['error']}")
            return
        
        embed = discord.Embed(
            title="Today's Narutodle Eye Challenge",
            description="Try to guess the character based on their eyes:",
            color=discord.Color.purple(),
            url=f"{self.base_url}/eye"
        )
        
        if result["image_url"]:
            embed.set_image(url=result["image_url"])
        
        embed.set_footer(text=f"Data retrieved at {result['timestamp']}")
        await ctx.send(embed=embed)
        
    @narutodle.command(name="refresh")
    async def narutodle_refresh(self, ctx):
        """Force refresh all Narutodle cached data (Admin only)."""
        # Check if user has permission to run admin commands
        if not self._check_permissions(ctx, admin_only=True):
            await ctx.send("⛔ You don't have permission to refresh the cache. This requires administrator permissions.")
            return
            
        await ctx.typing()
        
        if self.redis:
            try:
                # Get all narutodle keys
                narutodle_keys = await self.redis.keys("narutodle:*")
                image_keys = await self.redis.keys("image:*")
                
                # Delete keys
                if narutodle_keys:
                    await self.redis.delete(*narutodle_keys)
                if image_keys:
                    await self.redis.delete(*image_keys)
                    
                self.logger.info("Redis cache cleared via refresh command")
                await ctx.send("✅ Narutodle data has been refreshed! Use any command to get fresh data.")
            except Exception as e:
                self.logger.error(f"Redis error while refreshing cache: {e}")
                await ctx.send(f"❌ Error refreshing data: {e}")
        else:
            await ctx.send("❌ Redis is not connected. Cannot refresh cache.")
            
    @narutodle.group(name="admin", invoke_without_command=True)
    async def narutodle_admin(self, ctx):
        """Admin commands for Narutodle (Admin only)."""
        if not self._check_permissions(ctx, admin_only=True):
            await ctx.send("⛔ You don't have permission to use admin commands. This requires administrator permissions.")
            return
            
        await ctx.send("Available admin commands: `!narutodle admin stats`, `!narutodle admin clear_cache`, `!narutodle admin clear_stats`")
        
    @narutodle_admin.command(name="stats")
    async def narutodle_stats(self, ctx):
        """Get statistics about the cache and requests (Admin only)."""
        if not self._check_permissions(ctx, admin_only=True):
            await ctx.send("⛔ You don't have permission to view stats. This requires administrator permissions.")
            return
            
        await ctx.typing()
        
        if not self.redis:
            await ctx.send("❌ Redis is not connected. Cannot retrieve statistics.")
            return
        
        try:
            # Count keys in Redis by type
            narutodle_keys = len(await self.redis.keys("narutodle:*"))
            image_keys = len(await self.redis.keys("image:*"))
            stats_keys = len(await self.redis.keys("stats:*"))
            leaderboard_keys = len(await self.redis.keys("leaderboard:*"))
            
            # Get character count
            character_count = await self.redis.scard("narutodle:characters")
            
            # Create an embed with statistics
            embed = discord.Embed(
                title="Narutodle Bot Statistics",
                description="Current cache and database statistics",
                color=discord.Color.blue()
            )
            
            # Add Redis info
            embed.add_field(
                name="Redis Cache",
                value=f"Narutodle data entries: {narutodle_keys}\n"
                      f"Cached images: {image_keys}\n"
                      f"Character database: {character_count} characters\n"
                      f"User stats entries: {stats_keys}\n"
                      f"Leaderboard entries: {leaderboard_keys}",
                inline=True
            )
            
            # Add rate limit info
            embed.add_field(
                name="Rate Limiting",
                value=f"Recent requests: {len(self.request_timestamps)}\n"
                      f"Limit: {self.rate_limit} per {self.rate_limit_period}s\n"
                      f"Min interval: {self.min_request_interval}s",
                inline=True
            )
            
            # Add active games info
            embed.add_field(
                name="Active Games",
                value=f"Current active games: {len(self.active_games)}",
                inline=True
            )
            
            # Add timestamps
            embed.set_footer(text=f"Current time: {datetime.utcnow().isoformat()}")
            
            await ctx.send(embed=embed)
            
        except Exception as e:
            self.logger.error(f"Error getting admin stats: {e}")
            await ctx.send(f"❌ Error retrieving statistics: {e}")
        
    @narutodle_admin.command(name="clear_cache")
    async def narutodle_clear_cache(self, ctx):
        """Clear the entire cache (Admin only)."""
        if not self._check_permissions(ctx, admin_only=True):
            await ctx.send("⛔ You don't have permission to clear the cache. This requires administrator permissions.")
            return
            
        await ctx.typing()
        
        if not self.redis:
            await ctx.send("❌ Redis is not connected. Cannot clear cache.")
            return
            
        try:
            # Get all narutodle and image keys
            narutodle_keys = await self.redis.keys("narutodle:*")
            image_keys = await self.redis.keys("image:*")
            
            # Delete keys
            keys_deleted = 0
            if narutodle_keys:
                keys_deleted += await self.redis.delete(*narutodle_keys)
            if image_keys:
                keys_deleted += await self.redis.delete(*image_keys)
                
            await ctx.send(f"✅ Cache cleared! Deleted {keys_deleted} entries from Redis.")
            
        except Exception as e:
            self.logger.error(f"Redis error while clearing cache: {e}")
            await ctx.send(f"❌ Error clearing cache: {e}")
            
    @narutodle_admin.command(name="clear_stats")
    async def narutodle_clear_stats(self, ctx, confirm: str = None):
        """Clear all user statistics (Admin only, requires confirmation)."""
        if not self._check_permissions(ctx, admin_only=True):
            await ctx.send("⛔ You don't have permission to clear stats. This requires administrator permissions.")
            return
            
        if not confirm or confirm.lower() != "confirm":
            await ctx.send("⚠️ This will delete ALL user statistics and leaderboards. "
                          "This action cannot be undone! "
                          "Type `!narutodle admin clear_stats confirm` to proceed.")
            return
            
        await ctx.typing()
        
        if not self.redis:
            await ctx.send("❌ Redis is not connected. Cannot clear statistics.")
            return
            
        try:
            # Get all stats and leaderboard keys
            stats_keys = await self.redis.keys("stats:*")
            leaderboard_keys = await self.redis.keys("leaderboard:*")
            played_keys = await self.redis.keys("played:*")
            
            # Delete keys
            keys_deleted = 0
            if stats_keys:
                keys_deleted += await self.redis.delete(*stats_keys)
            if leaderboard_keys:
                keys_deleted += await self.redis.delete(*leaderboard_keys)
            if played_keys:
                keys_deleted += await self.redis.delete(*played_keys)
                
            await ctx.send(f"✅ All user statistics have been cleared! Deleted {keys_deleted} entries from Redis.")
            
        except Exception as e:
            self.logger.error(f"Redis error while clearing statistics: {e}")
            await ctx.send(f"❌ Error clearing statistics: {e}")
            
    @narutodle.group(name="play", invoke_without_command=True)
    async def narutodle_play(self, ctx):
        """Start playing Narutodle in Discord."""
        await ctx.send("Choose a mode to play: `!narutodle play classic`, `!narutodle play jutsu`, `!narutodle play quote`, or `!narutodle play eye`")
        
    @narutodle_play.command(name="classic")
    async def narutodle_play_classic(self, ctx):
        """Play the classic Narutodle mode."""
        await self._start_game(ctx, "classic")
        
    @narutodle_play.command(name="jutsu")
    async def narutodle_play_jutsu(self, ctx):
        """Play the jutsu Narutodle mode."""
        await self._start_game(ctx, "jutsu")
        
    @narutodle_play.command(name="quote")
    async def narutodle_play_quote(self, ctx):
        """Play the quote Narutodle mode."""
        await self._start_game(ctx, "quote")
        
    @narutodle_play.command(name="eye")
    async def narutodle_play_eye(self, ctx):
        """Play the eye Narutodle mode."""
        await self._start_game(ctx, "eye")
        
    async def _start_game(self, ctx, mode):
        """Start a Narutodle game session for a user.
        
        Args:
            ctx: Command context
            mode: Game mode to play
        """
        user_id = ctx.author.id
        guild_id = ctx.guild.id
        channel_id = ctx.channel.id
        
        # Check if user already played today
        if await self._check_already_played(user_id, guild_id, mode):
            await ctx.send(f"⚠️ You've already played the {mode} mode today! Try again tomorrow or try a different mode.")
            return
            
        # Check if user already has an active game of this mode
        game_key = f"{guild_id}_{channel_id}_{user_id}_{mode}"
        if game_key in self.active_games:
            await ctx.send(f"⚠️ You already have an active {mode} game! Finish that one first or use `!narutodle cancel` to cancel it.")
            return
            
        # Get the current challenge
        result = await self.get_current_narutodle(mode, refresh=False)
        if "error" in result:
            await ctx.send(f"Error: {result['error']}")
            return
            
        # Create embed to show the challenge
        embed = await self._create_game_embed(ctx, mode, result)
        
        # Store game state
        self.active_games[game_key] = {
            "mode": mode,
            "user_id": user_id,
            "guild_id": guild_id,
            "channel_id": channel_id,
            "start_time": time.time(),
            "attempts": 0,
            "max_attempts": 6,
            "data": result,
            "message_id": None
        }
        
        # Send the challenge
        message = await ctx.send(
            f"{ctx.author.mention}, I've started a Narutodle {mode} challenge for you! You have {self.active_games[game_key]['max_attempts']} attempts to guess the character. Type your answer or `!narutodle cancel` to quit.",
            embed=embed
        )
        
        # Store the message ID for future reference
        self.active_games[game_key]["message_id"] = message.id
        
    async def _create_game_embed(self, ctx, mode, data):
        """Create an embed for the game challenge.
        
        Args:
            ctx: Command context
            mode: Game mode
            data: Challenge data
            
        Returns:
            discord.Embed: Embed with the challenge
        """
        if mode == "classic":
            embed = discord.Embed(
                title="Narutodle Classic Challenge",
                description="Guess the Naruto character based on these attributes:",
                color=discord.Color.orange()
            )
            
            # Add properties to the embed
            for prop_name, prop_value in data["data"].items():
                embed.add_field(name=prop_name, value=prop_value, inline=True)
                
        elif mode == "jutsu":
            embed = discord.Embed(
                title="Narutodle Jutsu Challenge",
                description="Which character uses this jutsu?",
                color=discord.Color.blue()
            )
            
            if data["image_url"]:
                embed.set_image(url=data["image_url"])
                
        elif mode == "quote":
            embed = discord.Embed(
                title="Narutodle Quote Challenge",
                description="Who said this quote?",
                color=discord.Color.green()
            )
            
            if data["clue"]:
                embed.add_field(name="Quote", value=data["clue"], inline=False)
            
            # Add additional info if available
            if "recipient" in data["data"]:
                embed.add_field(name="Said to", value=data["data"]["recipient"], inline=True)
            
            if "arc" in data["data"]:
                embed.add_field(name="Arc", value=data["data"]["arc"], inline=True)
                
        elif mode == "eye":
            embed = discord.Embed(
                title="Narutodle Eye Challenge",
                description="Whose eyes are these?",
                color=discord.Color.purple()
            )
            
            if data["image_url"]:
                embed.set_image(url=data["image_url"])
                
        # Add attempts footer
        embed.set_footer(text=f"You have 6 attempts remaining | Type your answer or '!narutodle cancel' to quit")
        
        return embed
        
    @narutodle.command(name="cancel")
    async def narutodle_cancel(self, ctx):
        """Cancel your active Narutodle game."""
        user_id = ctx.author.id
        guild_id = ctx.guild.id
        channel_id = ctx.channel.id
        
        # Find user's active games in this channel
        active_game_keys = [k for k in self.active_games.keys() if k.startswith(f"{guild_id}_{channel_id}_{user_id}_")]
        
        if not active_game_keys:
            await ctx.send("You don't have any active games in this channel.")
            return
            
        # Cancel all active games
        for key in active_game_keys:
            mode = self.active_games[key]["mode"]
            del self.active_games[key]
            
        await ctx.send("Your active Narutodle games have been canceled.")
        
    @narutodle.command(name="stats")
    async def narutodle_user_stats(self, ctx, user: discord.Member = None):
        """View Narutodle statistics for yourself or another user."""
        if user is None:
            user = ctx.author
            
        # Get user stats
        stats = await self._get_user_stats(user.id, ctx.guild.id)
        
        if stats["total_games"] == 0:
            await ctx.send(f"{user.display_name} hasn't played any Narutodle games yet!")
            return
            
        # Create embed
        embed = discord.Embed(
            title=f"Narutodle Stats for {user.display_name}",
            description=f"Total games played: {stats['total_games']}\n"
                        f"Correct answers: {stats['total_correct']}\n"
                        f"Accuracy: {round(stats['total_correct'] / stats['total_games'] * 100, 1)}%\n"
                        f"Average attempts: {stats['average_attempts']}",
            color=discord.Color.gold()
        )
        
        # Add mode-specific stats
        for mode in self.modes:
            if mode in stats["modes"] and stats["modes"][mode]["games"] > 0:
                mode_stats = stats["modes"][mode]
                embed.add_field(
                    name=f"{mode.capitalize()} Mode",
                    value=f"Games: {mode_stats['games']}\n"
                          f"Correct: {mode_stats['correct']}\n"
                          f"Accuracy: {round(mode_stats['correct'] / mode_stats['games'] * 100, 1)}%\n"
                          f"Avg attempts: {mode_stats['average_attempts']}",
                    inline=True
                )
                
        await ctx.send(embed=embed)
        
    @narutodle.command(name="leaderboard", aliases=["lb"])
    async def narutodle_leaderboard(self, ctx, mode: str = None):
        """View the Narutodle leaderboard for your server."""
        if mode and mode.lower() not in self.modes:
            await ctx.send(f"Invalid mode. Choose from: {', '.join(self.modes)}")
            return
            
        # Get leaderboard
        leaderboard = await self._get_leaderboard(ctx.guild.id, mode, 10)
        
        if not leaderboard:
            await ctx.send("No Narutodle games have been played in this server yet!")
            return
            
        # Create embed
        mode_str = f" - {mode.capitalize()} Mode" if mode else ""
        embed = discord.Embed(
            title=f"Narutodle Leaderboard{mode_str}",
            description=f"Top players in {ctx.guild.name}",
            color=discord.Color.gold()
        )
        
        # Add leaderboard entries
        for i, entry in enumerate(leaderboard):
            embed.add_field(
                name=f"{i+1}. {entry['username']}",
                value=f"Correct: {entry['correct']}/{entry['games']} ({entry['accuracy']}%)\n"
                      f"Avg attempts: {entry['avg_attempts']}",
                inline=(i % 2 == 0)  # Alternate inline positioning
            )
            
        await ctx.send(embed=embed)
        
    @commands.Cog.listener()
    async def on_message(self, message):
        """Listen for answers to active games."""
        # Ignore bot messages
        if message.author.bot:
            return
            
        # Check if this is a DM
        if not message.guild:
            return
            
        # Get context info
        user_id = message.author.id
        guild_id = message.guild.id
        channel_id = message.channel.id
        
        # Check if this user has active games in this channel
        active_game_keys = [k for k in self.active_games.keys() 
                          if k.startswith(f"{guild_id}_{channel_id}_{user_id}_")]
        
        if not active_game_keys:
            return
            
        # Only process if the message isn't a command
        ctx = await self.bot.get_context(message)
        if ctx.valid:
            return
            
        # Get the active game (use the first one if multiple exist)
        game_key = active_game_keys[0]
        game = self.active_games[game_key]
        
        # Check if the guess is correct
        guess = message.content.strip().lower()
        
        # Process the guess
        await self._process_guess(message, game_key, guess)
        
    async def _process_guess(self, message, game_key, guess):
        """Process a user's guess in a Narutodle game.
        
        Args:
            message: Discord message with the guess
            game_key: Key for the active game
            guess: User's guess (text)
        """
        game = self.active_games[game_key]
        mode = game["mode"]
        
        # Increment attempts
        game["attempts"] += 1
        attempts_left = game["max_attempts"] - game["attempts"]
        
        # Get the answer (first try to extract from data, then fallback to common characters)
        naruto_characters = [
            "naruto uzumaki", "sasuke uchiha", "sakura haruno", "kakashi hatake",
            "itachi uchiha", "hinata hyuga", "neji hyuga", "rock lee", 
            "gaara", "shikamaru nara", "ino yamanaka", "choji akimichi",
            "jiraiya", "tsunade", "orochimaru", "kabuto yakushi",
            "pain", "konan", "madara uchiha", "obito uchiha",
            "minato namikaze", "kushina uzumaki", "might guy", "yamato",
            "sai", "shino aburame", "kiba inuzuka", "tenten",
            "temari", "kankuro", "hashirama senju", "tobirama senju",
            "hiruzen sarutobi", "kurama", "kisame hoshigaki", "deidara",
            "sasori", "hidan", "kakuzu", "zabuza momochi",
            "haku", "kimimaro", "anko mitarashi", "asuma sarutobi",
            "kurenai yuhi", "iruka umino", "shizune", "danzo shimura",
            "killer bee", "a (fourth raikage)", "mei terumi", "onoki"
        ]
        
        # Check if we've fetched the correct answer already
        answer = None
        if "answer" in game:
            answer = game["answer"].lower()
        
        # If we don't have an answer, try to determine it
        if not answer:
            # For classic mode, try to extract from the character data
            if mode == "classic" and "Name" in game["data"]["data"]:
                answer = game["data"]["data"]["Name"].lower()
            else:
                # For other modes, try to get from Redis if available
                if self.redis:
                    try:
                        today = datetime.utcnow().strftime('%Y-%m-%d')
                        daily_key = f"daily:{mode}:{today}"
                        stored_answer = await self.redis.get(daily_key)
                        if stored_answer:
                            answer = stored_answer.decode('utf-8').lower()
                    except Exception as e:
                        self.logger.error(f"Redis error getting answer: {e}")
                
                # If we still don't have an answer, choose default or random
                if not answer:
                    # In a real implementation, this would scrape the actual answer
                    # For demo purposes, we'll use a default or random character
                    if mode == "jutsu":
                        answer = "naruto uzumaki"  # Default for demo
                    elif mode == "quote":
                        answer = "kakashi hatake"  # Default for demo
                    elif mode == "eye":
                        answer = "sasuke uchiha"  # Default for demo
                    else:
                        # Fallback to random character
                        answer = random.choice(naruto_characters)
            
            # Store the answer in the game state
            game["answer"] = answer
            
            # Record in Redis for future reference
            await self._record_daily_character(mode, answer)
        
        # Check if the guess is correct with fuzzy matching
        is_correct = False
        
        # Exact match
        if guess == answer:
            is_correct = True
        
        # Check with common variations (e.g., "naruto" matches "naruto uzumaki")
        elif any(character for character in naruto_characters if 
                (character.startswith(guess) or guess.startswith(character)) and
                (len(guess) >= 5 and len(character) >= 5)):
            # This is a partial match, like "naruto" instead of "naruto uzumaki"
            # If the guess is the first part of the correct answer, count it as correct
            if answer.startswith(guess) or guess.startswith(answer):
                is_correct = True
        
        # Simple fuzzy matching for minor typos
        elif answer in guess or guess in answer:
            ratio = min(len(guess), len(answer)) / max(len(guess), len(answer))
            if ratio > 0.8:  # 80% similar
                is_correct = True
                
        # Handle the result of the guess
        if is_correct:
            # User guessed correctly
            await message.add_reaction("✅")
            
            # Build success message
            if game["attempts"] == 1:
                result_msg = f"🎉 **Amazing!** You guessed it on your first try!"
            elif game["attempts"] <= 3:
                result_msg = f"🎉 **Excellent!** You guessed it in just {game['attempts']} attempts!"
            else:
                result_msg = f"🎉 **Good job!** You guessed it in {game['attempts']} attempts!"
                
            embed = discord.Embed(
                title=f"Correct! The answer was {answer.title()}",
                description=result_msg,
                color=discord.Color.green()
            )
            
            await message.channel.send(embed=embed)
            
            # Record the successful guess in Redis
            await self._record_user_answer(
                user_id=game["user_id"],
                guild_id=game["guild_id"],
                mode=mode,
                correct=1,
                attempts=game["attempts"]
            )
            
            # Remove the game from active games
            del self.active_games[game_key]
            
        elif attempts_left <= 0:
            # User has used all attempts
            await message.add_reaction("❌")
            
            embed = discord.Embed(
                title=f"Game Over! The answer was {answer.title()}",
                description="You've used all your attempts. Better luck next time!",
                color=discord.Color.red()
            )
            
            await message.channel.send(embed=embed)
            
            # Record the failed attempt in Redis
            await self._record_user_answer(
                user_id=game["user_id"],
                guild_id=game["guild_id"],
                mode=mode,
                correct=0,
                attempts=game["max_attempts"]
            )
            
            # Remove the game from active games
            del self.active_games[game_key]
            
        else:
            # Incorrect guess but still has attempts remaining
            await message.add_reaction("❌")
            
            # Update the embed with remaining attempts
            try:
                channel = message.channel
                original_message = await channel.fetch_message(game["message_id"])
                
                embed = original_message.embeds[0]
                embed.set_footer(text=f"You have {attempts_left} attempts remaining | Type your answer or '!narutodle cancel' to quit")
                
                await original_message.edit(embed=embed)
                
            except Exception as e:
                self.logger.error(f"Error updating game embed: {e}")
                
    @narutodle.command(name="help")
    async def narutodle_help(self, ctx):
        """Get help with Narutodle commands."""
        embed = discord.Embed(
            title="Narutodle Bot Help",
            description="Commands for interacting with Narutodle challenges",
            color=discord.Color.gold()
        )
        
        # View commands
        embed.add_field(
            name="View Commands",
            value=(
                "`!narutodle classic [refresh]` - View classic character challenge\n"
                "`!narutodle jutsu [refresh]` - View jutsu challenge with image\n"
                "`!narutodle quote [refresh]` - View quote challenge\n"
                "`!narutodle eye [refresh]` - View eye challenge with image\n"
                "Add 'true' after any command to refresh the data"
            ),
            inline=False
        )
        
        # Play commands
        embed.add_field(
            name="Play Commands",
            value=(
                "`!narutodle play classic` - Play classic mode\n"
                "`!narutodle play jutsu` - Play jutsu mode\n"
                "`!narutodle play quote` - Play quote mode\n"
                "`!narutodle play eye` - Play eye mode\n"
                "`!narutodle cancel` - Cancel an active game"
            ),
            inline=False
        )
        
        # Stats commands
        embed.add_field(
            name="Stats Commands",
            value=(
                "`!narutodle stats [user]` - View your stats or another user's\n"
                "`!narutodle leaderboard [mode]` - View server leaderboard\n"
                "`!narutodle refresh` - Force refresh cached data (Admin only)"
            ),
            inline=False
        )
        
        # Admin commands
        embed.add_field(
            name="Admin Commands",
            value=(
                "`!narutodle admin stats` - View bot statistics\n"
                "`!narutodle admin clear_cache` - Clear the entire cache\n"
                "`!narutodle admin clear_stats` - Clear all user statistics"
            ),
            inline=False
        )
        
        embed.set_footer(text="Play Narutodle at https://narutodle.net")
        await ctx.send(embed=embed)
        
async def setup(bot):
    """Add the cog to the bot."""
    # Create cog instance with Redis URL from environment
    redis_url = os.getenv("REDIS_URL", "redis://localhost:6379/0")
    await bot.add_cog(Narutodle(bot, redis_url))
