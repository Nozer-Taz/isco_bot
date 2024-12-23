import asyncpg
from datetime import datetime
import os
from dotenv import load_dotenv
import pytz
import logging

load_dotenv()

class Database:
    def __init__(self):
        self.pool = None

    async def create_pool(self):
        self.pool = await asyncpg.create_pool(
            user=os.getenv('DB_USER'),
            password=os.getenv('DB_PASS'),
            database=os.getenv('DB_NAME'),
            host=os.getenv('DB_HOST'),
            port=os.getenv('DB_PORT')
        )

    async def create_tables(self):
        async with self.pool.acquire() as conn:
            # Create users table
            await conn.execute('''
                CREATE TABLE IF NOT EXISTS users (
                    user_id BIGINT PRIMARY KEY,
                    phone_number VARCHAR(20),
                    first_name VARCHAR(100),
                    last_name VARCHAR(100),
                    registered_at TIMESTAMP WITHOUT TIME ZONE DEFAULT (NOW() AT TIME ZONE 'UTC')
                )
            ''')

            # Create events table
            await conn.execute('''
                CREATE TABLE IF NOT EXISTS events (
                    event_id SERIAL PRIMARY KEY,
                    title VARCHAR(200) NOT NULL,
                    description TEXT,
                    photo_id VARCHAR(200),
                    event_datetime TIMESTAMP WITHOUT TIME ZONE NOT NULL,
                    created_at TIMESTAMP WITHOUT TIME ZONE DEFAULT (NOW() AT TIME ZONE 'UTC'),
                    created_by BIGINT REFERENCES users(user_id)
                )
            ''')

            # Create notifications table to track sent notifications
            await conn.execute('''
                CREATE TABLE IF NOT EXISTS notifications (
                    id SERIAL PRIMARY KEY,
                    event_id INTEGER REFERENCES events(event_id),
                    user_id BIGINT REFERENCES users(user_id),
                    notification_type VARCHAR(20),
                    sent_at TIMESTAMP WITHOUT TIME ZONE DEFAULT (NOW() AT TIME ZONE 'UTC'),
                    UNIQUE(event_id, user_id, notification_type)
                )
            ''')

    async def add_user(self, user_id: int, phone_number: str, first_name: str, last_name: str):
        """Add a new user to the database."""
        async with self.pool.acquire() as conn:
            await conn.execute('''
                INSERT INTO users (user_id, phone_number, first_name, last_name)
                VALUES ($1, $2, $3, $4)
                ON CONFLICT (user_id) 
                DO UPDATE SET 
                    phone_number = EXCLUDED.phone_number,
                    first_name = EXCLUDED.first_name,
                    last_name = EXCLUDED.last_name,
                    registered_at = NOW()
            ''', user_id, phone_number, first_name, last_name)

    async def get_user(self, user_id: int):
        async with self.pool.acquire() as conn:
            return await conn.fetchrow('SELECT * FROM users WHERE user_id = $1', user_id)

    async def create_event(self, title: str, description: str, photo_id: str, 
                          event_datetime: datetime, created_by: int):
        # Convert to UTC for storage
        if event_datetime.tzinfo is not None:
            event_datetime = event_datetime.astimezone(pytz.UTC).replace(tzinfo=None)
            
        async with self.pool.acquire() as conn:
            return await conn.fetchval('''
                INSERT INTO events (title, description, photo_id, event_datetime, created_by)
                VALUES ($1, $2, $3, $4, $5)
                RETURNING event_id
            ''', title, description, photo_id, event_datetime, created_by)

    async def get_upcoming_events(self, hours_ahead: float = None):
        # Get current time in UTC
        utc_now = datetime.now(pytz.UTC).replace(tzinfo=None)
        timezone = pytz.timezone(os.getenv('TIMEZONE', 'Asia/Almaty'))
        
        async with self.pool.acquire() as conn:
            if hours_ahead is not None:
                rows = await conn.fetch('''
                    SELECT 
                        event_id,
                        title,
                        description,
                        photo_id,
                        event_datetime,
                        created_at,
                        created_by
                    FROM events 
                    WHERE event_datetime > $1 
                    AND event_datetime <= $1 + interval '1 hour' * $2
                    ORDER BY event_datetime
                ''', utc_now, hours_ahead)
            else:
                rows = await conn.fetch('''
                    SELECT 
                        event_id,
                        title,
                        description,
                        photo_id,
                        event_datetime,
                        created_at,
                        created_by
                    FROM events 
                    WHERE event_datetime > $1
                    ORDER BY event_datetime
                ''', utc_now)
            
            # Convert rows to dictionaries and add timezone information
            events = []
            for row in rows:
                event = dict(row)
                event['event_datetime'] = timezone.localize(event['event_datetime'])
                events.append(event)
            
            return events

    async def get_events_for_new_user(self, user_id: int):
        """Get all upcoming events that the user hasn't been notified about."""
        async with self.pool.acquire() as conn:
            # First, let's log what we're querying
            logging.info(f"Fetching events for new user {user_id}")
            
            # Get the current time in UTC
            current_time = datetime.now()
            logging.info(f"Current time: {current_time}")
            
            query = '''
                SELECT DISTINCT
                    e.event_id,
                    e.title,
                    e.description,
                    e.photo_id,
                    e.event_datetime,
                    e.created_at,
                    e.created_by
                FROM events e
                WHERE 
                    e.event_datetime > $1 AND
                    NOT EXISTS (
                        SELECT 1 
                        FROM notifications n 
                        WHERE n.event_id = e.event_id 
                        AND n.user_id = $2
                        AND n.notification_type = 'initial_notification'
                    )
                ORDER BY e.event_datetime
            '''
            
            rows = await conn.fetch(query, current_time, user_id)
            logging.info(f"Found {len(rows)} events for new user {user_id}")
            
            # Log each event found
            for row in rows:
                logging.info(f"Event found - ID: {row['event_id']}, "
                           f"Title: {row['title']}, "
                           f"DateTime: {row['event_datetime']}")
            
            return rows

    async def record_notification(self, event_id: int, user_id: int, notification_type: str):
        """Record that a notification was sent."""
        async with self.pool.acquire() as conn:
            try:
                await conn.execute('''
                    INSERT INTO notifications (event_id, user_id, notification_type)
                    VALUES ($1, $2, $3)
                    ON CONFLICT (event_id, user_id, notification_type) DO NOTHING
                ''', event_id, user_id, notification_type)
                logging.info(f"Recorded notification - Event: {event_id}, "
                           f"User: {user_id}, Type: {notification_type}")
            except Exception as e:
                logging.error(f"Error recording notification: {e}")
                raise

    async def get_all_users(self):
        """Get all registered users."""
        async with self.pool.acquire() as conn:
            rows = await conn.fetch('SELECT user_id FROM users')
            return [dict(row) for row in rows]
