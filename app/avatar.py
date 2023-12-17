"""
import os
import random
from datetime import datetime, timedelta
from apscheduler.schedulers.background import BackgroundScheduler

def generate_avatar():
    avatar_file = 'path_to_your_avatar_file'

    # If the avatar file exists and was modified less than a day ago, skip generation
    if os.path.exists(avatar_file) and datetime.now() - datetime.fromtimestamp(os.path.getmtime(avatar_file)) < timedelta(days=1):
        return

    # Your code to generate avatar image goes here

avatar_scheduler = BackgroundScheduler()

# Generate a random delay between 0 and 10 minutes
delay = random.randint(0, 10)

# Schedule the job to run every day at a specific time, with a random delay
avatar_scheduler.add_job(generate_avatar, 'interval', days=1, start_date=datetime.now() + timedelta(minutes=delay))

avatar_scheduler.start()
"""