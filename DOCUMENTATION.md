# Telegram Event Notification Bot Documentation

## Table of Contents
1. [Overview](#overview)
2. [Project Structure](#project-structure)
3. [Configuration](#configuration)
4. [Database](#database)
5. [Bot Features](#bot-features)
6. [Notification System](#notification-system)
7. [Customization Guide](#customization-guide)
8. [Troubleshooting](#troubleshooting)

## Overview

This Telegram bot manages events and sends notifications to registered users. It's built using:
- aiogram 2.25.1 (Telegram Bot Framework)
- PostgreSQL (Database)
- APScheduler (Notification Scheduling)

### Key Features
- User registration with phone number and name
- Event creation with title, description, photo, and datetime
- Automatic notifications at multiple intervals
- Admin-only event creation
- User-friendly datetime selection interface

## Project Structure

```
telegram_event_bot/
├── bot.py           # Main bot logic and handlers
├── database.py      # Database operations
├── requirements.txt # Project dependencies
├── .env            # Configuration file
└── README.md       # Basic setup instructions
```

## Configuration

### Environment Variables (.env)
```env
BOT_TOKEN=your_bot_token    # Get from @BotFather
ADMIN_ID=your_telegram_id   # Get from @userinfobot
DB_HOST=localhost           # PostgreSQL host
DB_PORT=5432               # PostgreSQL port
DB_NAME=notifications_bot   # Database name
DB_USER=your_db_user       # Database user
DB_PASS=your_db_password   # Database password
TIMEZONE=Asia/Almaty       # Your timezone
```

To modify these settings:
1. Edit the `.env` file
2. Restart the bot

### Timezone Configuration
The bot uses the timezone specified in `.env` for:
- Event creation
- Notification scheduling
- Time display

To change the timezone:
1. Update `TIMEZONE` in `.env`
2. Use standard timezone names from the [IANA Time Zone Database](https://en.wikipedia.org/wiki/List_of_tz_database_time_zones)

## Database

### Tables Structure

1. Users Table
```sql
CREATE TABLE users (
    user_id BIGINT PRIMARY KEY,
    phone_number VARCHAR(20),
    first_name VARCHAR(100),
    last_name VARCHAR(100),
    registered_at TIMESTAMP WITHOUT TIME ZONE DEFAULT (NOW() AT TIME ZONE 'UTC')
)
```

2. Events Table
```sql
CREATE TABLE events (
    event_id SERIAL PRIMARY KEY,
    title VARCHAR(200) NOT NULL,
    description TEXT,
    photo_id VARCHAR(200),
    event_datetime TIMESTAMP WITHOUT TIME ZONE NOT NULL,
    created_at TIMESTAMP WITHOUT TIME ZONE DEFAULT (NOW() AT TIME ZONE 'UTC'),
    created_by BIGINT REFERENCES users(user_id)
)
```

3. Notifications Table
```sql
CREATE TABLE notifications (
    id SERIAL PRIMARY KEY,
    event_id INTEGER REFERENCES events(event_id),
    user_id BIGINT REFERENCES users(user_id),
    notification_type VARCHAR(20),
    sent_at TIMESTAMP WITHOUT TIME ZONE DEFAULT (NOW() AT TIME ZONE 'UTC'),
    UNIQUE(event_id, user_id, notification_type)
)
```

### Database Operations
All database operations are in `database.py`. Key functions:

- `create_pool()`: Initializes database connection
- `create_tables()`: Creates required tables
- `add_user()`: Registers new users
- `create_event()`: Creates new events
- `get_upcoming_events()`: Retrieves future events
- `record_notification()`: Logs sent notifications

## Bot Features

### User Registration
Users must register before receiving notifications:
1. Send `/start`
2. Share phone number
3. Enter first name
4. Enter last name

To modify registration fields:
1. Update `Registration` class in `bot.py`
2. Update corresponding handlers
3. Modify database schema if needed

### Event Creation (Admin Only)
Events are created through a step-by-step process:

1. Title Input
```python
# Modify title validation in bot.py
@dp.message_handler(state=EventCreation.title)
async def process_title(message: types.Message, state: FSMContext):
    # Add your validation logic here
    async with state.proxy() as data:
        data['title'] = message.text
```

2. Description Input
```python
# Modify description handling
@dp.message_handler(state=EventCreation.description)
async def process_description(message: types.Message, state: FSMContext):
    # Add your validation or formatting here
```

3. Photo Upload
```python
# Modify photo handling
@dp.message_handler(content_types=['photo'], state=EventCreation.photo)
async def process_photo(message: types.Message, state: FSMContext):
    # Customize photo processing here
```

4. Date Selection
- Shows next 7 days as buttons
- Accepts custom date input
- Format: "DD Month" (e.g., "25 December")

To modify date options:
```python
def get_date_keyboard():
    keyboard = ReplyKeyboardMarkup(resize_keyboard=True)
    today = datetime.now()
    
    # Modify number of days shown
    days_to_show = 7
    for i in range(days_to_show):
        date = today + timedelta(days=i)
        button_text = date.strftime("%d %B (%A)")
        keyboard.add(types.KeyboardButton(button_text))
```

5. Time Selection
- Shows common times (09:00 - 20:00)
- Accepts custom time input
- 24-hour format

To modify time options:
```python
def get_time_keyboard():
    # Modify available time slots
    times = [
        "09:00", "10:00", "11:00", "12:00",
        "13:00", "14:00", "15:00", "16:00",
        "17:00", "18:00", "19:00", "20:00"
    ]
```

## Notification System

### Notification Intervals
Current intervals (modify in `schedule_event_notifications`):
```python
notification_times = [
    (timedelta(days=1), "Event starts in 1 day"),
    (timedelta(hours=6), "Event starts in 6 hours"),
    (timedelta(hours=1), "Event starts in 1 hour"),
    (timedelta(minutes=15), "Event starts in 15 minutes"),
    (timedelta(minutes=-15), "Event started 15 minutes ago")
]
```

### Scheduler Configuration
```python
scheduler = AsyncIOScheduler(
    timezone=os.getenv('TIMEZONE', 'Asia/Almaty'),
    job_defaults={
        'misfire_grace_time': 300,  # 5 minutes grace time
        'coalesce': True,           # Combine missed notifications
    }
)
```

### Notification Format
Modify the notification message in `send_notification`:
```python
async def send_notification(event_id, user_id, title, description, photo_id, notification_type):
    # Customize your notification message format here
    caption = f"🔔 Event Notification: {title}\n\n{description}\n\n{notification_type}"
```

## Customization Guide

### Adding New Features

1. Add new State:
```python
class EventCreation(StatesGroup):
    new_state = State()  # Add your new state here
```

2. Create new handler:
```python
@dp.message_handler(state=EventCreation.new_state)
async def process_new_state(message: types.Message, state: FSMContext):
    # Your handler logic here
```

### Modifying Notification Times
To change notification intervals:
1. Update `notification_times` in `schedule_event_notifications`
2. No other changes needed

### Adding Custom Commands
1. Create new handler:
```python
@dp.message_handler(commands=['your_command'])
async def your_command_handler(message: types.Message):
    # Your command logic here
```

### Modifying Database Schema
1. Update table creation in `database.py`
2. Add new methods for your operations
3. Update existing methods if needed

## Troubleshooting

### Common Issues

1. Timezone Errors
- Check `TIMEZONE` in `.env`
- Ensure all datetime objects are timezone-aware
- Use `timezone.localize()` for local times

2. Database Connections
- Verify PostgreSQL is running
- Check database credentials in `.env`
- Ensure database exists

3. Notification Issues
- Check scheduler configuration
- Verify timezone settings
- Check for error logs

### Logging
The bot uses Python's logging module:
```python
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
```

To modify logging:
1. Change log level (DEBUG, INFO, WARNING, ERROR)
2. Modify format string
3. Add file handler for persistent logs

### Error Handling
Main error handling is in:
- `on_startup()`: Bot initialization
- `schedule_event_notifications()`: Notification scheduling
- `send_notification()`: Notification sending

Add custom error handling:
```python
try:
    # Your code here
except Exception as e:
    logging.error(f"Custom error message: {e}")
    # Your error handling
```
