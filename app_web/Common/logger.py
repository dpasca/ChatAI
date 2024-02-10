import inspect
import os

# Enable for debugging purposes
ENABLE_LOGGING = os.getenv('FORCE_ENABLE_LOGGING', '0') == '1'
VERBOSE_LOGGING = os.getenv('VERBOSE_LOGGING', '0') == '1'

#==================================================================
def print_trimmed(msg):
    if len(msg) >150:
        print(msg[:150] + "...")
    else:
        print(msg)

def logmsg(msg):
    if ENABLE_LOGGING:
        caller = inspect.currentframe().f_back.f_code.co_name
        print_trimmed(f"[{caller}] {msg}")

def logwarn(msg):
    if ENABLE_LOGGING:
        caller = inspect.currentframe().f_back.f_code.co_name
        print(f"\033[93m[WARN]\033[0m[{caller}] {msg}")

def logerr(msg):
    if ENABLE_LOGGING:
        caller = inspect.currentframe().f_back.f_code.co_name
        print(f"\033[91m[ERR]\033[0m[{caller}] {msg}")
