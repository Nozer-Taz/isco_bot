import os
import logging
import asyncio
from datetime import datetime, timedelta
import pytz
from aiogram import Bot, Dispatcher, types
from aiogram.contrib.fsm_storage.memory import MemoryStorage
from aiogram.dispatcher import FSMContext
from aiogram.dispatcher.filters.state import State, StatesGroup
from aiogram.types import ParseMode, ReplyKeyboardMarkup, KeyboardButton
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from dotenv import load_dotenv
from database import Database

load_dotenv()

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)

# Initialize bot and dispatcher
bot = Bot(token=os.getenv('BOT_TOKEN'))
storage = MemoryStorage()
dp = Dispatcher(bot, storage=storage)
db = Database()

# Configure scheduler with timezone
scheduler = AsyncIOScheduler(
    timezone=os.getenv('TIMEZONE', 'Asia/Almaty'),
    job_defaults={
        'misfire_grace_time': 300,  # 5 minutes grace time for misfired jobs
        'coalesce': True,  # Combine multiple pending jobs into one
    }
)

timezone = pytz.timezone(os.getenv('TIMEZONE', 'Asia/Almaty'))

# States
class Registration(StatesGroup):
    phone_number = State()
    first_name = State()
    last_name = State()

class EventCreation(StatesGroup):
    title = State()
    description = State()
    photo = State()
    datetime = State()
    time = State()

# Keyboards
def get_phone_number_kb():
    keyboard = ReplyKeyboardMarkup(resize_keyboard=True, one_time_keyboard=True)
    keyboard.add(KeyboardButton(text="Share Phone Number", request_contact=True))
    return keyboard

def get_date_keyboard():
    keyboard = ReplyKeyboardMarkup(resize_keyboard=True)
    today = datetime.now()
    
    # Add next 7 days as buttons
    for i in range(7):
        date = today + timedelta(days=i)
        button_text = date.strftime("%d %B (%A)")
        keyboard.add(types.KeyboardButton(button_text))
    
    return keyboard

def get_time_keyboard():
    keyboard = types.ReplyKeyboardMarkup(resize_keyboard=True, row_width=4)
    
    # Common event times
    times = [
        "09:00", "10:00", "11:00", "12:00",
        "13:00", "14:00", "15:00", "16:00",
        "17:00", "18:00", "19:00", "20:00"
    ]
    
    # Add times in rows of 4
    buttons = [types.KeyboardButton(time) for time in times]
    keyboard.add(*buttons)
    
    return keyboard

def is_admin(user_id: int) -> bool:
    """Check if user is an admin."""
    return str(user_id) == os.getenv('ADMIN_ID')

# Start command
@dp.message_handler(commands=['start'])
async def start(message: types.Message):
    """Start command handler."""
    try:
        # Check if user is already registered
        user = await db.get_user(message.from_user.id)
        if user:
            await message.reply(
                "👋 Welcome back! You are already registered.\n"
                "Use /help to see available commands."
            )
            return

        await Registration.phone_number.set()
        await message.reply(
            "👋 Welcome! Please share your phone number to register.",
            reply_markup=get_phone_number_kb()
        )
    except Exception as e:
        logging.error(f"Error in start command: {e}")
        await message.reply("❌ An error occurred. Please try again later.")

@dp.message_handler(content_types=['contact', 'text'], state=Registration.phone_number)
async def process_phone_number(message: types.Message, state: FSMContext):
    """Process phone number from user."""
    try:
        if message.contact is not None:
            phone = message.contact.phone_number
        else:
            # Clean up phone number if entered as text
            phone = ''.join(filter(str.isdigit, message.text))
            if not phone:
                await message.reply(
                    "❌ Invalid phone number. Please share your contact or enter a valid phone number.",
                    reply_markup=get_phone_number_kb()
                )
                return
            
            # Add + if not present
            if not phone.startswith('+'):
                phone = '+' + phone

        # Save to state
        async with state.proxy() as data:
            data['phone_number'] = phone

        # Move to next state
        await Registration.first_name.set()
        await message.reply(
            "📝 Please enter your first name:",
            reply_markup=types.ReplyKeyboardRemove()
        )
    except Exception as e:
        logging.error(f"Error processing phone number: {e}")
        await message.reply("❌ An error occurred. Please try again.")

@dp.message_handler(state=Registration.first_name)
async def process_first_name(message: types.Message, state: FSMContext):
    """Process first name."""
    try:
        if not message.text or len(message.text) > 100:
            await message.reply("❌ Name must be between 1 and 100 characters.")
            return

        async with state.proxy() as data:
            data['first_name'] = message.text

        await Registration.last_name.set()
        await message.reply("📝 Please enter your last name:")
    except Exception as e:
        logging.error(f"Error processing first name: {e}")
        await message.reply("❌ An error occurred. Please try again.")

@dp.message_handler(state=Registration.last_name)
async def process_last_name(message: types.Message, state: FSMContext):
    """Process last name and complete registration."""
    try:
        if not message.text or len(message.text) > 100:
            await message.reply("❌ Last name must be between 1 and 100 characters.")
            return

        async with state.proxy() as data:
            # Register user
            await db.add_user(
                user_id=message.from_user.id,
                phone_number=data['phone_number'],
                first_name=data['first_name'],
                last_name=message.text
            )

        await state.finish()
        
        # Send registration confirmation
        await message.reply(
            "✅ Registration complete!\n\n"
            f"Phone: {data['phone_number']}\n"
            f"Name: {data['first_name']} {message.text}\n\n"
            "I'll now check for any upcoming events..."
        )
        
        # Schedule notifications for existing events
        await schedule_notifications_for_new_user(message.from_user.id)
        
    except asyncpg.exceptions.UniqueViolationError:
        logging.warning(f"Duplicate registration attempt for user {message.from_user.id}")
        await state.finish()
        await message.reply(
            "👋 You are already registered!\n"
            "Use /help to see available commands."
        )
    except Exception as e:
        logging.error(f"Error processing last name: {e}")
        await message.reply("❌ An error occurred. Please try again.")

# Admin commands
@dp.message_handler(commands=['create_event'])
async def create_event_start(message: types.Message):
    if message.from_user.id != int(os.getenv('ADMIN_ID')):
        await message.reply("Sorry, only admin can create events.")
        return
    
    await message.reply("Please enter the event title:")
    await EventCreation.title.set()

@dp.message_handler(state=EventCreation.title)
async def process_title(message: types.Message, state: FSMContext):
    async with state.proxy() as data:
        data['title'] = message.text
    await message.reply("Please enter the event description:")
    await EventCreation.description.set()

@dp.message_handler(state=EventCreation.description)
async def process_description(message: types.Message, state: FSMContext):
    async with state.proxy() as data:
        data['description'] = message.text
    await message.reply("Please send a photo for the event:")
    await EventCreation.photo.set()

@dp.message_handler(content_types=['photo'], state=EventCreation.photo)
async def process_photo(message: types.Message, state: FSMContext):
    async with state.proxy() as data:
        data['photo_id'] = message.photo[-1].file_id
    
    # Create a custom keyboard for date selection
    keyboard = get_date_keyboard()
    
    await message.reply(
        "Please select or enter the event date in format: DD Month (Day)\n"
        "For example: 25 December (Monday)\n\n"
        "You can select from the quick options below or type your own:",
        reply_markup=keyboard
    )
    await EventCreation.datetime.set()

@dp.message_handler(state=EventCreation.datetime)
async def process_date(message: types.Message, state: FSMContext):
    try:
        # Store the date temporarily
        async with state.proxy() as data:
            # Try to parse the date
            try:
                # First, try to parse the date in the format "DD Month (Day)"
                date_str = message.text.split('(')[0].strip()
                data['event_date'] = datetime.strptime(date_str, "%d %B").replace(year=datetime.now().year)
            except ValueError:
                await message.reply(
                    "Invalid date format. Please use format: DD Month\n"
                    "For example: 25 December"
                )
                return
        
        # Create a custom keyboard for time selection
        keyboard = get_time_keyboard()
        
        await message.reply(
            "Please select or enter the event time in 24-hour format (HH:MM)\n"
            "For example: 14:30 for 2:30 PM\n\n"
            "You can select from common times below or type your own:",
            reply_markup=keyboard
        )
        await EventCreation.time.set()
        
    except ValueError:
        await message.reply(
            "Invalid date format. Please use format: DD Month\n"
            "For example: 25 December"
        )

async def send_notification(event_id: int, title: str, description: str, 
                          photo_id: str, notification_type: str):
    """Send a notification about an event."""
    try:
        users = await db.get_all_users()
        message_text = (
            f"🔔 Event Reminder 🔔\n\n"
            f"📌 {title}\n"
            f"📝 {description}\n\n"
            f"⏰ {notification_type}"
        )
        
        for user in users:
            try:
                await bot.send_photo(
                    chat_id=user['user_id'],
                    photo=photo_id,
                    caption=message_text,
                    parse_mode=ParseMode.HTML
                )
                await db.record_notification(event_id, user['user_id'], notification_type)
                logging.info(f"Notification sent to user {user['user_id']} for event {event_id}")
            except Exception as e:
                logging.error(f"Failed to send notification to user {user['user_id']}: {e}")
    except Exception as e:
        logging.error(f"Failed to process notification for event {event_id}: {e}")

async def send_event_creation_notification(event_id: int, title: str, description: str, 
                                         photo_id: str, event_datetime: datetime):
    """Send notification about new event to all users."""
    users = await db.get_all_users()
    
    # Format the message
    message_text = (
        f"🎉 New Event Created! 🎉\n\n"
        f"📌 Title: {title}\n"
        f"📅 Date: {event_datetime.strftime('%d %B %Y (%A)')}\n"
        f"⏰ Time: {event_datetime.strftime('%H:%M')}\n\n"
        f"📝 Description:\n{description}\n\n"
        f"See you there! 🤝"
    )
    
    # Send to all users
    for user in users:
        try:
            await bot.send_photo(
                chat_id=user['user_id'],
                photo=photo_id,
                caption=message_text,
                parse_mode=ParseMode.HTML
            )
            logging.info(f"Event creation notification sent to user {user['user_id']}")
        except Exception as e:
            logging.error(f"Failed to send event creation notification to user {user['user_id']}: {e}")

async def schedule_event_notifications(event_id: int, event_datetime: datetime, 
                                    title: str, description: str, photo_id: str):
    notification_times = [
        (timedelta(days=1), "Event starts in 1 day"),
        (timedelta(hours=6), "Event starts in 6 hours"),
        (timedelta(hours=1), "Event starts in 1 hour"),
        (timedelta(minutes=15), "Event starts in 15 minutes"),
        (timedelta(minutes=-15), "Event started 15 minutes ago")
    ]
    
    # Ensure event_datetime is timezone-aware
    local_tz = pytz.timezone(os.getenv('TIMEZONE', 'Asia/Almaty'))
    if event_datetime.tzinfo is None:
        event_datetime = local_tz.localize(event_datetime)
    
    # Get current time with timezone
    now = datetime.now(local_tz)
    
    for time_delta, notification_text in notification_times:
        notification_time = event_datetime - time_delta
        
        # Ensure notification_time is timezone-aware
        if notification_time.tzinfo is None:
            notification_time = local_tz.localize(notification_time)
            
        if notification_time > now:
            # Create a unique job ID for each notification
            job_id = f"event_{event_id}_notification_{time_delta}"
            
            # Add the job with error handling
            try:
                scheduler.add_job(
                    send_notification,
                    'date',
                    run_date=notification_time,
                    args=[event_id, title, description, photo_id, notification_text],
                    id=job_id,
                    replace_existing=True  # Replace if job already exists
                )
                logging.info(f"Scheduled notification for event {event_id} at {notification_time}")
            except Exception as e:
                logging.error(f"Failed to schedule notification: {e}")

async def schedule_notifications_for_new_user(user_id: int):
    """Schedule notifications for all upcoming events for a new user."""
    try:
        logging.info(f"Starting notification scheduling for new user {user_id}")
        
        # Get all upcoming events the user hasn't been notified about
        events = await db.get_events_for_new_user(user_id)
        logging.info(f"Retrieved {len(events)} events for user {user_id}")
        
        if not events:
            logging.info(f"No upcoming events found for user {user_id}")
            await bot.send_message(
                user_id,
                "👋 Welcome! There are no upcoming events at the moment.\n"
                "You'll receive notifications when new events are created!"
            )
            return
            
        # Send welcome message with number of upcoming events
        event_word = "event" if len(events) == 1 else "events"
        welcome_msg = (
            f"🎉 Welcome! There are {len(events)} upcoming {event_word}.\n"
            "I'll send you the details now..."
        )
        await bot.send_message(user_id, welcome_msg)
        logging.info(f"Sent welcome message to user {user_id}")
        
        # Send each event to the user
        for event in events:
            try:
                logging.info(f"Processing event {event['event_id']} for user {user_id}")
                
                event_time = event['event_datetime']
                if isinstance(event_time, str):
                    event_time = datetime.fromisoformat(event_time)
                
                # Format the message
                message_text = (
                    f"📅 Upcoming Event:\n\n"
                    f"📌 Title: {event['title']}\n"
                    f"⏰ Date: {event_time.strftime('%d %B %Y (%A)')}\n"
                    f"🕒 Time: {event_time.strftime('%H:%M')}\n\n"
                    f"📝 Description:\n{event['description']}"
                )
                
                # Send event details
                await bot.send_photo(
                    chat_id=user_id,
                    photo=event['photo_id'],
                    caption=message_text,
                    parse_mode=ParseMode.HTML
                )
                logging.info(f"Sent event details for event {event['event_id']} to user {user_id}")
                
                # Record the initial notification
                await db.record_notification(
                    event['event_id'],
                    user_id,
                    "initial_notification"
                )
                logging.info(f"Recorded initial notification for event {event['event_id']}, user {user_id}")
                
                # Schedule future notifications
                notification_times = [
                    (timedelta(days=1), "Event starts in 1 day"),
                    (timedelta(hours=6), "Event starts in 6 hours"),
                    (timedelta(hours=1), "Event starts in 1 hour"),
                    (timedelta(minutes=15), "Event starts in 15 minutes"),
                    (timedelta(minutes=-15), "Event started 15 minutes ago")
                ]
                
                # Get current time with timezone
                local_tz = pytz.timezone(os.getenv('TIMEZONE', 'Asia/Almaty'))
                now = datetime.now(local_tz)
                
                for time_delta, notification_text in notification_times:
                    notification_time = event_time - time_delta
                    
                    # Ensure notification_time is timezone-aware
                    if notification_time.tzinfo is None:
                        notification_time = local_tz.localize(notification_time)
                        
                    if notification_time > now:
                        # Create a unique job ID for each notification
                        job_id = f"event_{event['event_id']}_user_{user_id}_notification_{time_delta}"
                        
                        scheduler.add_job(
                            send_notification,
                            'date',
                            run_date=notification_time,
                            args=[event['event_id'], event['title'], event['description'], 
                                 event['photo_id'], notification_text],
                            id=job_id,
                            replace_existing=True
                        )
                        logging.info(f"Scheduled {notification_text} for event {event['event_id']}, "
                                   f"user {user_id} at {notification_time}")
                
            except Exception as e:
                logging.error(f"Error processing event {event['event_id']} for user {user_id}: {e}")
                continue
                
    except Exception as e:
        logging.error(f"Error in schedule_notifications_for_new_user for user {user_id}: {e}")
        # Try to notify the user about the error
        try:
            await bot.send_message(
                user_id,
                "❌ Sorry, there was an error processing events. "
                "Please contact the administrator."
            )
        except:
            pass

@dp.message_handler(state=EventCreation.time)
async def process_time(message: types.Message, state: FSMContext):
    try:
        # Parse the time
        try:
            time = datetime.strptime(message.text, "%H:%M").time()
        except ValueError:
            await message.reply(
                "Invalid time format. Please use 24-hour format (HH:MM)\n"
                "For example: 14:30 for 2:30 PM"
            )
            return
        
        async with state.proxy() as data:
            # Combine date and time
            event_datetime = datetime.combine(data['event_date'], time)
            
            # Add timezone information
            local_tz = pytz.timezone(os.getenv('TIMEZONE', 'Asia/Almaty'))
            event_datetime = local_tz.localize(event_datetime)
            
            # Check if the datetime is in the past
            if event_datetime < datetime.now(local_tz):
                if event_datetime.date() == datetime.now(local_tz).date():
                    await message.reply(
                        "You cannot create an event for a time that has already passed today. "
                        "Please select a future time:",
                        reply_markup=get_time_keyboard()
                    )
                else:
                    await message.reply(
                        "You cannot create an event in the past. Please select a future date:",
                        reply_markup=get_date_keyboard()
                    )
                return
            
            # Create the event
            event_id = await db.create_event(
                data['title'],
                data['description'],
                data['photo_id'],
                event_datetime,
                message.from_user.id
            )
            
            # Format the confirmation message
            confirmation_msg = (
                f"✅ Event created successfully!\n\n"
                f"📌 Title: {data['title']}\n"
                f"📅 Date: {event_datetime.strftime('%d %B %Y (%A)')}\n"
                f"⏰ Time: {event_datetime.strftime('%H:%M')}\n"
                f"📝 Description: {data['description']}"
            )
            
            # Send confirmation to admin
            await message.reply(confirmation_msg, reply_markup=types.ReplyKeyboardRemove())
            
            # Send notification to all users
            await send_event_creation_notification(
                event_id,
                data['title'],
                data['description'],
                data['photo_id'],
                event_datetime
            )
            
            # Schedule notifications
            await schedule_event_notifications(
                event_id,
                event_datetime,
                data['title'],
                data['description'],
                data['photo_id']
            )
            
            await state.finish()
            
    except Exception as e:
        await message.reply(
            "Something went wrong. Please try again or contact support.\n"
            f"Error: {str(e)}"
        )

@dp.message_handler(commands=['list_events'])
async def list_events(message: types.Message):
    """List all upcoming events. Only available to admins."""
    if not is_admin(message.from_user.id):
        await message.reply("⛔️ This command is only available to administrators.")
        return

    try:
        # Get all upcoming events
        events = await db.get_upcoming_events()
        
        if not events:
            await message.reply("📅 No upcoming events found.")
            return
        
        # Sort events by datetime
        events.sort(key=lambda x: x['event_datetime'])
        
        # Format the response
        response = "📋 Upcoming Events:\n\n"
        
        for i, event in enumerate(events, 1):
            event_time = event['event_datetime']
            
            # Calculate time until event
            now = datetime.now(event_time.tzinfo)
            time_until = event_time - now
            days_until = time_until.days
            hours_until = time_until.seconds // 3600
            minutes_until = (time_until.seconds % 3600) // 60
            
            # Format time until string
            time_until_str = []
            if days_until > 0:
                time_until_str.append(f"{days_until} days")
            if hours_until > 0:
                time_until_str.append(f"{hours_until} hours")
            if minutes_until > 0:
                time_until_str.append(f"{minutes_until} minutes")
            time_until_formatted = ", ".join(time_until_str) if time_until_str else "Starting now!"
            
            response += (
                f"{i}. 📌 {event['title']}\n"
                f"   📅 {event_time.strftime('%d %B %Y (%A)')}\n"
                f"   ⏰ {event_time.strftime('%H:%M')}\n"
                f"   ⏳ Time until: {time_until_formatted}\n"
                f"   📝 {event['description']}\n\n"
            )
        
        # Split message if it's too long
        if len(response) > 4096:
            parts = [response[i:i+4096] for i in range(0, len(response), 4096)]
            for part in parts:
                await message.reply(part)
        else:
            await message.reply(response)
            
    except Exception as e:
        logging.error(f"Error listing events: {e}")
        await message.reply("❌ An error occurred while fetching events. Please try again later.")

@dp.message_handler(commands=['help'])
async def help_command(message: types.Message):
    """Show available commands."""
    is_user_admin = is_admin(message.from_user.id)
    
    help_text = (
        "🤖 Available Commands:\n\n"
        "/start - Start the bot and register\n"
        "/help - Show this help message\n"
    )
    
    if is_user_admin:
        help_text += (
            "\n👑 Admin Commands:\n"
            "/create_event - Create a new event\n"
            "/list_events - List all upcoming events\n"
        )
    
    await message.reply(help_text)

async def on_startup(dp):
    try:
        # Initialize database
        await db.create_pool()
        await db.create_tables()
        
        # Start the scheduler
        scheduler.start()
        
        # Schedule notifications for all upcoming events
        events = await db.get_upcoming_events()
        
        for event in events:
            await schedule_event_notifications(
                event['event_id'],
                event['event_datetime'],
                event['title'],
                event['description'],
                event['photo_id']
            )
            
        logging.info("Bot started successfully")
    except Exception as e:
        logging.error(f"Error during startup: {e}")
        raise  # Re-raise the exception to prevent the bot from starting with errors

async def on_shutdown(dp):
    # Properly shut down the scheduler
    scheduler.shutdown()
    logging.info("Bot shutdown complete")

if __name__ == '__main__':
    from aiogram import executor
    
    # Start the bot with both startup and shutdown handlers
    executor.start_polling(
        dp,
        on_startup=on_startup,
        on_shutdown=on_shutdown,
        skip_updates=True
    )
