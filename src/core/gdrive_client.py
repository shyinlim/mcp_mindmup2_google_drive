import asyncio
import base64
import functools
import json
import os
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from google.oauth2 import service_account
from googleapiclient.discovery import build
from src.model.common_model import OperationResult
from src.utility.logger import get_logger

logger = get_logger(__name__)


class GoogleDriveClient:
    def __init__(self):
        self.service = None  # GDrive API service item
        self.credential = None
        self._executor = ThreadPoolExecutor(max_workers=5)  # Async workers

    async def run_sync(self, func, *args, **kwargs):
        """
        Run an asynchronous coroutine synchronously.

        Args:
          coro: The coroutine to execute
        Returns:
          The result of the coroutine execution
        Note:
          This method bridges async/await code with synchronous code by running the coroutine in the current event loop.
      """

        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(
            executor=self._executor,
            func=functools.partial(func, *args, **kwargs)
        )

    async def _test_auth_connection(self):
        try:
            result = await self.run_sync(
                lambda: self.service.about().get(fields='user, storageQuota').execute()
            )
            user_email = result.get('user', {}).get('emailAddress', 'Unknown')
            logger.info(f'GDrive _test_auth_connection success: {user_email}')
        except Exception as e:
            raise Exception(f'GDrive _test_auth_connection error: {e}') from e

    async def authenticate(self) -> OperationResult:
        try:

            # region Get credential file
            logger.info('Authenticate with Google Drive')
            cred_file = os.getenv('GOOGLE_DRIVE_CREDENTIAL_FILE')

            if not cred_file:
                # If code cannot extract credential then try to extract from
                # default location
                default_path = [
                    'deployment/credentials/google_service_account.json',
                    'credentials/google_service_account.json',
                    'google_service_account.json'
                ]

                for path in default_path:
                    if Path(path).exists():
                        cred_file = path
                        logger.info(
                            f'Using credential from default location: {cred_file}')
                        break

            if not cred_file or not Path(cred_file).exists():
                return OperationResult.fail(
                    detail=f'Credential file not found: {cred_file}.')
            # endregion Get credential file

            # region Google console item's permission
            scope = [
                'https://www.googleapis.com/auth/drive',  # Overall GDrive accesss
                'https://www.googleapis.com/auth/drive.file'  # File access
            ]

            self.credential = service_account.Credentials.from_service_account_file(
                filename=cred_file,
                scopes=scope
            )

            # Build GDrive
            self.service = build('drive', 'v3', credentials=self.credential)

            # Check connection
            await self._test_auth_connection()
            return OperationResult.success(detail='Authenticate success.')
            # endregion Google console item's permission

        except Exception as e:
            error_message = f'GDrive authenticate error: {e}'
            logger.error(error_message)
            return OperationResult.fail(detail=error_message)

    async def authenticate_from_base64(self, credential_base64: str) -> OperationResult:
        """Authenticate using base64 encoded service account JSON.

        Args:
            credential_base64: Base64 encoded service account JSON string.

        Returns:
            OperationResult indicating success or failure.
        """
        try:
            # Decode base64 to JSON string
            credential_bytes = base64.b64decode(credential_base64)
            credential_json = credential_bytes.decode('utf-8')
            credential_dict = json.loads(credential_json)

            # Define scopes
            scopes = [
                'https://www.googleapis.com/auth/drive',
                'https://www.googleapis.com/auth/drive.file'
            ]

            # Build credential from dict (not file)
            self.credential = service_account.Credentials.from_service_account_info(
                credential_dict,
                scopes=scopes
            )

            # Build GDrive service
            self.service = build('drive', 'v3', credentials=self.credential)

            # Check connection
            await self._test_auth_connection()
            return OperationResult.success(detail='Authenticate from base64 success.')

        except Exception as e:
            error_message = f'GDrive authenticate_from_base64 error: {e}'
            logger.error(error_message)
            return OperationResult.fail(detail=error_message)
