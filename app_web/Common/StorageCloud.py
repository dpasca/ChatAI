#==================================================================
# StorageCloud.py
#
# Author: Davide Pasca, 2023/12/23
# Desc: Storage class for DigitalOcean Spaces
#==================================================================
import os
from io import BytesIO
import boto3
from boto3.s3.transfer import S3Transfer, TransferConfig  # Make sure to add this line
from botocore.exceptions import ClientError
from datetime import datetime, timezone
import tempfile
import shutil
#import logging
#boto3.set_stream_logger('boto3.resources', level=logging.DEBUG)
from botocore.exceptions import ClientError
from .logger import *
from concurrent import futures

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

    def download_file_multipart(self, local_path, cloud_path, part_size=10*1024*1024, max_workers=5):
        # Ensure the directory exists
        os.makedirs(os.path.dirname(local_path), exist_ok=True)

        # Get the total size of the file
        obj = self.s3.head_object(Bucket=self.bucket, Key=cloud_path)
        file_size = obj['ContentLength']

        # Calculate the number of parts
        parts = (file_size + part_size - 1) // part_size

        # Inner function to access `self` and download a part
        def download_part(part_number):
            start_byte = part_number * part_size
            end_byte = min((part_number + 1) * part_size - 1, file_size - 1)
            range_header = f"bytes={start_byte}-{end_byte}"
            response = self.s3.get_object(Bucket=self.bucket, Key=cloud_path, Range=range_header)
            # Open the file in append binary mode to write the downloaded part
            with open(local_path, 'r+b' if os.path.exists(local_path) else 'wb') as file:
                file.seek(start_byte)
                file.write(response['Body'].read())

        with futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
            logmsg(f"Downloading {cloud_path} to {local_path} in {parts} parts...")
            futures_list = [executor.submit(download_part, part) for part in range(parts)]
            for future in futures.as_completed(futures_list):
                future.result()  # Wait for each part to download

    def does_file_match_cloud(self, local_path, cloud_path):
        # Get cloud file's size and last modification time
        cloud_object = self.s3.head_object(Bucket=self.bucket, Key=cloud_path)
        cloud_size = cloud_object['ContentLength']
        cloud_dt = cloud_object['LastModified']

        # Get local file's size and modification time
        local_size = os.path.getsize(local_path)
        local_mtime = os.path.getmtime(local_path)
        local_dt = datetime.fromtimestamp(local_mtime, timezone.utc)

        return cloud_dt <= local_dt and local_size == cloud_size

    def download_file(self, local_path, cloud_path, only_if_newer=True):
        if only_if_newer and os.path.exists(local_path) and self.does_file_match_cloud(local_path, cloud_path):
            logmsg(f"Local file {local_path} is up-to-date. Skipping download.")
            return

        try:
            self.download_file_multipart(local_path, cloud_path)
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
                # Exclude obvious nuisance files
                if filename == ".DS_Store":
                    continue
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
