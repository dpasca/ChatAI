#==================================================================
# StorageCloud.py
#
# Author: Davide Pasca, 2023/12/23
# Desc: Storage class for DigitalOcean Spaces
#==================================================================
import os
from io import BytesIO
import boto3
from datetime import datetime, timezone
#import logging
#boto3.set_stream_logger('boto3.resources', level=logging.DEBUG)
from botocore.exceptions import ClientError
from .logger import *

class StorageCloud:
    def __init__(self, bucket, access_key, secret_key, endpoint):
        self.bucket = bucket
        self.access_key = access_key
        self.secret_key = secret_key
        self.endpoint = endpoint
        self.s3 = self.createStorage()

    def createStorage(self):
        logmsg("Creating storage...")
        s3 = boto3.client(
            's3',
            aws_access_key_id=self.access_key,
            aws_secret_access_key=self.secret_key,
            endpoint_url=self.endpoint
        )
        return s3

    def FileExists(self, object_name):
        try:
            self.s3.head_object(Bucket=self.bucket, Key=object_name)
            return True
        except ClientError:
            return False

    def upload_file(self, data_bytes, object_name):
        logmsg(f"Uploading file {object_name}...")
        self.s3.upload_fileobj(
            data_bytes,
            self.bucket,
            object_name,
            ExtraArgs={'ACL': 'public-read'}
        )

    def download_file(self, local_path, cloud_path, only_if_newer=True):
        try:
            if only_if_newer:
                # Check if local file exists and get its modification time
                if os.path.exists(local_path):
                    local_mtime = os.path.getmtime(local_path)
                    local_dt = datetime.fromtimestamp(local_mtime, timezone.utc)
                else:
                    local_dt = datetime.fromtimestamp(0, timezone.utc)  # Epoch if file doesn't exist

                # Get cloud file's last modification time
                cloud_object = self.s3.head_object(Bucket=self.bucket, Key=cloud_path)
                cloud_dt = cloud_object['LastModified']

                # Compare modification times and download if cloud is newer
                if cloud_dt > local_dt:
                    logmsg(f"Cloud file {cloud_path} is newer. Downloading...")
                    # Directly call S3 download without the newer check to avoid recursion
                    os.makedirs(os.path.dirname(local_path), exist_ok=True)
                    with open(local_path, 'wb') as file:
                        self.s3.download_fileobj(self.bucket, cloud_path, file)
                else:
                    logmsg(f"Local file {local_path} is up-to-date. Skipping download.")
            else:
                # If only_if_newer is False, proceed to download without checking
                logmsg(f"Downloading file {cloud_path} to {local_path} without date check...")
                os.makedirs(os.path.dirname(local_path), exist_ok=True)
                with open(local_path, 'wb') as file:
                    self.s3.download_fileobj(self.bucket, cloud_path, file)
        except ClientError as e:
            if e.response['Error']['Code'] == 'NoSuchKey':
                logerr(f"File {cloud_path} does not exist in the cloud storage.")
            else:
                raise e

    def upload_dir(self, local_dir, target_dir, use_file_listing=False):
        logmsg(f"Uploading directory {local_dir} to {target_dir}...")
        file_list = []
        for root, dirs, files in os.walk(local_dir):
            for filename in files:
                local_path = os.path.join(root, filename)
                relative_path = os.path.relpath(local_path, local_dir)
                cloud_path = os.path.join(target_dir, relative_path)
                with open(local_path, 'rb') as data:
                    self.upload_file(data, cloud_path)
                file_list.append(cloud_path)

        if use_file_listing:
            # Create the file listing
            file_listing_path = os.path.join(target_dir, "file_listing.txt")
            file_listing_content = "\n".join(file_list)
            file_listing_bytes = BytesIO(file_listing_content.encode('utf-8'))
            self.upload_file(file_listing_bytes, file_listing_path)

    def download_dir(self, local_dir, cloud_dir, use_file_listing=False):
        logmsg(f"Downloading directory {cloud_dir} to {local_dir}...")
        if use_file_listing:
            file_listing_path = os.path.join(cloud_dir, "file_listing.txt")
            local_file_listing_path = os.path.join(local_dir, "file_listing.txt")
            self.download_file(local_file_listing_path, file_listing_path)
            if os.path.exists(local_file_listing_path):
                with open(local_file_listing_path, 'r') as file:
                    file_list = file.read().split("\n")
                for cloud_path in file_list:
                    if not cloud_path:
                        continue
                    local_path = os.path.join(local_dir, os.path.relpath(cloud_path, cloud_dir))
                    self.download_file(local_path, cloud_path)
            else:
                logerr(f"File listing {file_listing_path} does not exist in the cloud storage.")
        else:
            paginator = self.s3.get_paginator('list_objects_v2')
            try:
                for page in paginator.paginate(Bucket=self.bucket, Prefix=cloud_dir):
                    for obj in page.get('Contents', []):
                        key = obj['Key']
                        if key.endswith('/'):
                            continue  # Skip directories
                        file_path = os.path.join(local_dir, key[len(cloud_dir):].lstrip('/'))
                        self.download_file(file_path, key)
            except ClientError as e:
                if e.response['Error']['Code'] == 'NoSuchKey':
                    logerr(f"Directory {cloud_dir} does not exist in the cloud storage.")
                else:
                    raise e

    def ScanDir(self, cloud_dir):
        logmsg(f"Scanning directory '{cloud_dir}' in the cloud...")
        paginator = self.s3.get_paginator('list_objects_v2')
        # Ensure we have the correct string for the prefix
        prefix = cloud_dir.rstrip('/') + ('/' if cloud_dir else '')
        try:
            for page in paginator.paginate(Bucket=self.bucket, Prefix=prefix):
                for obj in page.get('Contents', []):
                    key = obj['Key']
                    logmsg(f"Found cloud object: {key}")
        except ClientError as e:
            logerr(f"An error occurred while scanning directory '{cloud_dir}': {e}" +
                   f" Full-path: {self.bucket}/{prefix}")

    def GetFileURL(self, object_name):
        logmsg(f"Getting file url for {object_name}...")
        try:
            url = f"{self.endpoint}/{self.bucket}/{object_name}"
            return url
        except Exception as e:
            logerr(e)
            return None
