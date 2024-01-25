#==================================================================
# StorageCloud.py
#
# Author: Davide Pasca, 2023/12/23
# Desc: Storage class for DigitalOcean Spaces
#==================================================================
import os
import inspect
import boto3
from botocore.exceptions import ClientError

class StorageCloud:
    def __init__(self, bucket, ENABLE_LOGGING=False):
        self.bucket = bucket
        self.ENABLE_LOGGING = ENABLE_LOGGING

        self.s3 = self.createStorage()

    def createStorage(self):
        self.logmsg("Creating storage...")
        s3 = boto3.client(
            's3',
            aws_access_key_id=os.getenv("DO_SPACES_ACCESS_KEY"),
            aws_secret_access_key=os.getenv("DO_SPACES_SECRET_KEY"),
            endpoint_url=os.getenv("DO_STORAGE_SERVER")
        )
        return s3

    def FileExists(self, object_name):
        try:
            self.s3.head_object(Bucket=self.bucket, Key=object_name)
            return True
        except ClientError:
            return False

    def UploadFile(self, data_bytes, object_name):
        self.logmsg(f"Uploading file {object_name}...")
        self.s3.upload_fileobj(
            data_bytes,
            self.bucket,
            object_name,
            ExtraArgs={'ACL': 'public-read'}
        )

    #def download_file(self, file_path, object_name):
    #    with open(file_path, "wb") as file:
    #        self.s3.download_fileobj(self.bucket, object_name, file)

    def GetFileURL(self, object_name):
        self.logmsg(f"Getting file url for {object_name}...")
        try:
            url = f"{os.getenv('DO_STORAGE_SERVER')}/{self.bucket}/{object_name}"
            return url
        except Exception as e:
            self.logerr(e)
            return None

    def logmsg(self, msg):
        if self.ENABLE_LOGGING:
            caller = inspect.currentframe().f_back.f_code.co_name
            print(f"[{caller}] {msg}")

    def logerr(self, msg):
        if self.ENABLE_LOGGING:
            caller = inspect.currentframe().f_back.f_code.co_name
            print(f"\033[91m[ERR]\033[0m[{caller}] {msg}")
