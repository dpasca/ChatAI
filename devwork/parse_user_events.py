import re
from collections import defaultdict
from datetime import datetime

# Configuration
LOG_FILE_PATH = '/var/log/gunicorn/access.log'  # Update this path as needed
TIME_FORMAT = '%d/%b/%Y:%H:%M:%S %z'

# Updated regex pattern to make CustomClientId optional
log_pattern = re.compile(
    r'(?:CustomClientId=(?P<client_id>[\w-]+))?.*?\[(?P<timestamp>.*?)\] "(?P<method>POST|GET) (?P<endpoint>/api/user_info|/get_history) HTTP/1\.\d" (?P<status>\d{3})'
)

def parse_logs():
    hourly_events = defaultdict(lambda: defaultdict(int))  # Dictionary to store counts per hour
    user_events = defaultdict(lambda: defaultdict(list))  # Nested defaultdict for endpoints

    print(f"Parsing logs from {LOG_FILE_PATH}")
    
    with open(LOG_FILE_PATH, 'r') as log_file:
        for line in log_file:
            match = log_pattern.search(line)
            if match:
                timestamp_str = match.group('timestamp')
                endpoint = match.group('endpoint')
                status = int(match.group('status'))

                # Parse timestamp
                timestamp = datetime.strptime(timestamp_str, TIME_FORMAT)
                hour = timestamp.replace(minute=0, second=0, microsecond=0)  # Round to the hour

                # Only track successful requests (status 200)
                if status == 200:
                    user_events['Unknown'][endpoint].append(timestamp)
                    hourly_events[hour][endpoint] += 1

    # Display event summary by hour
    print("\nHourly call frequency:")
    for hour, events in sorted(hourly_events.items()):
        print(f"{hour.strftime('%Y-%m-%d %H:%M:%S')} UTC")
        for endpoint, count in events.items():
            print(f"  - {endpoint}: {count} calls")

    # Display total event summary
    print("\nTotal event summary:")
    for endpoint, times in user_events['Unknown'].items():
        print(f"  - {endpoint}: {len(times)} times, last at {max(times).strftime(TIME_FORMAT) if times else 'N/A'}")

if __name__ == "__main__":
    parse_logs()
