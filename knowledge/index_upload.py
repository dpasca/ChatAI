# Load the environment variables, override the existing ones
from dotenv import load_dotenv
load_dotenv(override=True)

import os
import paramiko

# Update the path for the modules below
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from app_web.Common.logger import *

# Directory for persisting llmaindex index data
INDEX_PERSIST_DIR = "_index_data"
# Directory for persisting Chroma data
CHROMA_PERSIST_DIR = "_chroma_db"

def upload_to_server(local_dir, remote_dir, hostname, username, key_filename=None):

    unwanted_file_patterns = [
        ".DS_Store",
        ".gitignore",
        "file_listing.txt"
    ]

    ssh = paramiko.SSHClient()
    ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())

    if key_filename:
        ssh.connect(hostname, username=username, key_filename=key_filename)
    else:
        ssh.connect(hostname, username=username)

    sftp = ssh.open_sftp()

    # Create remote directory if it doesn't exist
    try:
        sftp.stat(remote_dir)
    except FileNotFoundError:
        logmsg(f"Creating remote directory: {remote_dir}")
        mkdir_recursive(sftp, remote_dir)

    for root, dirs, files in os.walk(local_dir):
        for dir in dirs:
            local_path = os.path.join(root, dir)
            remote_path = os.path.join(remote_dir, os.path.relpath(local_path, local_dir))
            try:
                sftp.stat(remote_path)
            except FileNotFoundError:
                logmsg(f"Creating directory: {remote_path}")
                sftp.mkdir(remote_path)

        for file in files:
            if any([unwanted in file for unwanted in unwanted_file_patterns]):
                continue
            local_path = os.path.join(root, file)
            remote_path = os.path.join(remote_dir, os.path.relpath(local_path, local_dir))
            logmsg(f"Uploading file: {local_path} -> {remote_path}")
            sftp.put(local_path, remote_path)

    sftp.close()
    ssh.close()

def mkdir_recursive(sftp, remote_dir):
    dirs = remote_dir.split('/')
    current_dir = ''
    for dir in dirs:
        current_dir += f'{dir}/'
        try:
            sftp.stat(current_dir)
        except FileNotFoundError:
            try:
                print(f"Creating directory: {current_dir}")
                sftp.mkdir(current_dir)
            except PermissionError as e:
                print(f"Permission denied while creating directory: {current_dir}")
                print(f"Error: {str(e)}")
                raise

#===================================================================
import argparse

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--remote_server", type=str, required=True, default=None, help="Remote server address")
    parser.add_argument(
        "--remote_path", type=str, required=True, default=None, help="Remote path for index and chroma db")
    parser.add_argument(
        "--remote_user", type=str, default="flask", help="Remote user")
    args = parser.parse_args()

    if False: # Do a test query
        test_query(
            INDEX_PERSIST_DIR,
            CHROMA_PERSIST_DIR,
            "ricetta di marmellata alle fragole")

    # Upload to remote server
    # NOTE: this assume that the remote repo is located in /home/args.remote_user/args.remote_path/
    #  With the DB dirs as:
    #   - /home/args.remote_user/args.remote_path/_index_data
    #   - /home/args.remote_user/args.remote_path/_chroma_db

    upload_to_server(
        INDEX_PERSIST_DIR,
        os.path.join(args.remote_path, INDEX_PERSIST_DIR),
        args.remote_server,
        args.remote_user
    )
    upload_to_server(
        CHROMA_PERSIST_DIR,
        os.path.join(args.remote_path, CHROMA_PERSIST_DIR),
        args.remote_server,
        args.remote_user
    )
