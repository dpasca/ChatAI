import inspect
import os

# Enable for debugging purposes
ENABLE_LOGGING = os.getenv('FORCE_ENABLE_LOGGING', '0') == '1'
VERBOSE_LOGGING = os.getenv('VERBOSE_LOGGING', '1') == '1'

COL_RESET     = "\033[0m"
COL_BOLD      = "\033[1m"
COL_UNDERLINE = "\033[4m"
COL_GRAY      = "\033[90m"
COL_RED       = "\033[91m"
COL_GREEN     = "\033[92m"
COL_YELLOW    = "\033[93m"
COL_BLUE      = "\033[94m"
COL_PURPLE    = "\033[95m"
COL_CYAN      = "\033[96m"
COL_WHITE     = "\033[97m"
COL_ORANGE    = "\033[33m"
COL_MAGENTA   = "\033[35m"

#==================================================================
def make_color(color, msg):
    return f"{color}{msg}{COL_RESET}"

def make_caller(caller):
    COLS_FOR_CALLER = [
        COL_GREEN     ,
        COL_YELLOW    ,
        COL_BLUE      ,
        COL_PURPLE    ,
        COL_CYAN      ,
        COL_WHITE     ,
        COL_ORANGE    ,
        COL_MAGENTA   ,
    ]
    COLS_N = len(COLS_FOR_CALLER)
    # Some random number for the caller
    caller_idx = hash(caller) % COLS_N
    col = COLS_FOR_CALLER[caller_idx]

    return f"[{make_color(col, caller)}]"

def apply_highlight(msg):
    SC_COL = COL_YELLOW
    NUM_COL = COL_GREEN
    SC_LIST = set("\\$%^&*()_+=[]{}|;:'\",.<>/?")
    NUM_LIST = set("0123456789")

    ESC_SEQ_START = "\033["
    ESC_SEQ_END = "m"
    RESET_SEQ = "\033[0m"

    in_escape_seq = False
    out_msg_parts = []

    i = 0
    while i < len(msg):
        if msg[i:i+len(ESC_SEQ_START)] == ESC_SEQ_START:
            # Detected the start of an escape sequence
            in_escape_seq = True
            seq_end_idx = msg.find(ESC_SEQ_END, i) + 1

            # Add the entire escape sequence
            out_msg_parts.append(msg[i:seq_end_idx])

            if msg[i:seq_end_idx] == RESET_SEQ:
                # Reset if it's the reset sequence
                in_escape_seq = False

            i = seq_end_idx  # Move past the escape sequence
        else:
            if not in_escape_seq:
                # Apply coloring only if not in an escape sequence
                if msg[i] in SC_LIST:
                    out_msg_parts.append(make_color(SC_COL, msg[i]))
                elif msg[i] in NUM_LIST:
                    out_msg_parts.append(make_color(NUM_COL, msg[i]))
                else:
                    out_msg_parts.append(msg[i])
            else:
                # If in an escape sequence, just add the character without modification
                out_msg_parts.append(msg[i])
            i += 1  # Move to the next character

    return ''.join(out_msg_parts)


def print_trimmed(msg):
    if not VERBOSE_LOGGING and len(msg) > 150:
        msg = msg[:150]

    # Split before the first `:` and after
    idx = msg.find(':')
    if idx > 0:
        p1 = msg[:idx]
        p2 = apply_highlight(msg[idx+1:])
        # check if p1 already has color
        if "\033" not in p1:
            print(f"{make_color(COL_CYAN, p1)}:{p2}")
            return

    print(apply_highlight(msg))


def logmsg(msg):
    if ENABLE_LOGGING:
        caller = inspect.currentframe().f_back.f_code.co_name
        print_trimmed(f"{make_caller(caller)} {msg}")

def logwarn(msg):
    if ENABLE_LOGGING:
        caller = inspect.currentframe().f_back.f_code.co_name
        print(f"{make_color(COL_ORANGE, '[WARN]')}[{caller}] {msg}")

def logerr(msg):
    if ENABLE_LOGGING:
        caller = inspect.currentframe().f_back.f_code.co_name
        print(f"{make_color(COL_RED, '[ERR]')}[{caller}] {msg}")
