from http.cookies import SimpleCookie
from http import HTTPStatus
from typing import List, Optional
import aiohttp
import json
import base64
import logging

from galaxy.http import create_client_session, handle_exception
from galaxy.api.errors import UnknownBackendResponse, UnknownError

from model.download import TroveDownload


class AuthorizedHumbleAPI:
    _AUTHORITY = "https://www.humblebundle.com/"
    _PROCESS_LOGIN = "processlogin"
    _ORDER_LIST_URL = "api/v1/user/order"
    _ORDER_URL = "/api/v1/order/{}"

    TROVES_PER_CHUNK = 20
    _SUBSCRIPTION_HOME = 'subscription/home'
    _SUBSCRIPTION_TROVE = 'subscription/trove'
    _TROVE_CHUNK_URL = 'api/v1/trove/chunk?index={}'
    _TROVE_DOWNLOAD_SIGN_URL = 'api/v1/user/download/sign'
    _TROVE_REDEEM_DOWNLOAD = 'humbler/redeemdownload'

    _DEFAULT_PARAMS = {"ajax": "true"}
    _DEFAULT_HEADERS = {
        "Accept": "application/json",
        "Accept-Charset": "utf-8",
        "Keep-Alive": "true",
        "User-Agent": "Apache-HttpClient/UNAVAILABLE (java 1.4)"
    }

    def __init__(self):
        self._session = create_client_session(headers=self._DEFAULT_HEADERS)

    @property
    def is_authenticated(self) -> bool:
        logging.debug(f'is authenticated? {bool(self._session.cookie_jar)}')
        return bool(self._session.cookie_jar)

    async def _request(self, method, path, *args, **kwargs):
        url = self._AUTHORITY + path
        logging.debug(f'{method}, {url}, {args}, {kwargs}')
        if 'params' not in kwargs:
            kwargs['params'] = self._DEFAULT_PARAMS
        with handle_exception():
            return await self._session.request(method, url, *args, **kwargs)

    async def _is_session_valid(self):
        """Simply asks about order list to know if session is valid.
        galaxy.api.errors instances cannot be catched so galaxy.http.handle_excpetion
        is the final check with all the logic under its context.
        """
        with handle_exception():
            try:
                await self._session.request('get', self._AUTHORITY + self._ORDER_LIST_URL)
            except aiohttp.ClientResponseError as e:
                if e.status == HTTPStatus.UNAUTHORIZED:
                    return False
                raise
        return True

    def _decode_user_id(self, _simpleauth_sess):
        info = _simpleauth_sess.split('|')[0]
        info += '=='  # ensure full padding
        decoded = json.loads(base64.b64decode(info))
        return decoded['user_id']

    async def authenticate(self, auth_cookie: dict) -> Optional[str]:
        # recreate original cookie
        cookie = SimpleCookie()
        cookie_val = bytes(auth_cookie['value'], "utf-8").decode("unicode_escape")
        # some users have cookies with escaped characters, some not...
        # for the first group strip quotes:
        cookie_val = cookie_val.replace('"', '')
        cookie[auth_cookie['name']] = cookie_val

        user_id = self._decode_user_id(cookie_val)
        self._session.cookie_jar.update_cookies(cookie)

        if await self._is_session_valid():
            return user_id
        return None

    async def get_gamekeys(self) -> List[str]:
        res = await self._request('get', self._ORDER_LIST_URL)
        parsed = await res.json()
        logging.info(f"The order list:\n{parsed}")
        gamekeys = [it["gamekey"] for it in parsed]
        return gamekeys

    async def get_order_details(self, gamekey) -> dict:
        res = await self._request('get', self._ORDER_URL.format(gamekey), params={
            'all_tpkds': 'true'
        })
        return await res.json()

    async def _get_trove_details(self, chunk_index) -> list:
        res = await self._request('get', self._TROVE_CHUNK_URL.format(chunk_index))
        return await res.json()

    async def had_trove_subscription(self) -> bool:
        """Based on current behavior of `humblebundle.com/subscription/home`
        that is accesable only by "current and former subscribers"
        """
        res = await self._request('get', self._SUBSCRIPTION_HOME, allow_redirects=False)
        if res.status == 200:
            return True
        elif res.status == 302:
            return False
        else:
            logging.warning(f'{self._SUBSCRIPTION_HOME}, Status code: {res.status}')
            return False
    
    async def get_montly_trove_data(self) -> dict:
        """Parses a subscription/trove page to find list of recently added games.
        Returns json containing "newlyAdded" trove games and "standardProducts" that is 
        the same like output from api/v1/trove/chunk/index=0
        "standardProducts" may not contain "newlyAdded" sometimes
        """
        res = await self._request('get', self._SUBSCRIPTION_TROVE)
        txt = await res.text()
        search = '<script id="webpack-monthly-trove-data" type="application/json">'
        json_start = txt.find(search) + len(search)
        candidate = txt[json_start:].strip()
        parsed, _ = json.JSONDecoder().raw_decode(candidate)
        return parsed
    
    async def get_trove_details(self, from_chunk: int=0):
        troves: List[str] = []
        index = from_chunk
        while True:
            chunk_details = await self._get_trove_details(index)
            if type(chunk_details) != list:
                logging.debug(f'chunk_details: {chunk_details}')
                raise UnknownBackendResponse()
            elif len(chunk_details) == 0:
                logging.debug('No more chunk pages')
                break
            troves += chunk_details
            index += 1
        return troves

    async def _get_trove_signed_url(self, download: TroveDownload):
        res = await self._request('post', self._TROVE_DOWNLOAD_SIGN_URL, params={
            'machine_name': download.machine_name,
            'filename': download.web
        })
        return await res.json()

    async def _reedem_trove_download(self, download: TroveDownload, product_machine_name: str):
        """Unknown purpose - humble http client do this after post for signed_url
        Response should be text with {'success': True} if everything is OK
        """
        res = await self._request('post', self._TROVE_REDEEM_DOWNLOAD, params={
            'download': download.machine_name,
            'download_page': "false",  # TODO check what it does
            'product': product_machine_name
        })
        content = await res.read()
        if content != b"{'success': True}":
            logging.error(f'unexpected response while reedem trove download: {content}')
            raise UnknownError()

    async def get_trove_sign_url(self, download: TroveDownload, product_machine_name: str):
        urls = await self._get_trove_signed_url(download)
        await self._reedem_trove_download(download, product_machine_name)
        return urls

    async def close_session(self):
        await self._session.close()
