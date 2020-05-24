import os as _os
import sys as _sys

import re as _re
import requests as _requests
import time as _time

import brotli as _brotli
import gzip as _gzip
import zlib as _zlib

# _ used before module names to prevent importing of them from outside
# this module.


class Downloader():

    def __init__(self, url: str, path: str = None, method: str = "GET", cookies: dict = None) -> None:
        self.url = url
        self.path = path
        self.request_method = method
        self.session_cookies = cookies
        self.is_resume = False
        self.session = _requests.Session()
        self.content_request = None
        self.title_fetched = None
        self.filesize = None
        self.filesize_humanized = None
        self.local_filesize = None
        self.destination = None
        self.fname = None

        if self.session_cookies is not None:
            self.session.cookies.update(self.session_cookies)

    @staticmethod
    def humanize_bytes(nbytes: int) -> str:
        '''Convert amount of bytes to human readable form.
        '''
        suffix = {0: " B",
                  1: " KB",
                  2: " MB",
                  3: " GB"}
        i = 0
        while (nbytes // 1024 > 0) and (i < 3):
            nbytes = round(nbytes / 1024, 2)
            i += 1
        return str(nbytes) + suffix.get(i)

    def path_handler(self, path: str, default: str, url: str, rename: bool = 0) -> tuple:
        '''Handles validation of the complete path.
        '''
        destination, fname = _os.path.split(path)
        destination = "./" if destination == "" else destination
        while(not _os.path.isdir(destination)):
            temp_destination = str(
                input("Destination non-existant:[Current: %s] " % destination))
            destination = destination if temp_destination is "" else temp_destination
        if fname == "" or rename:
            print("Enter valid file name\nFile name:", fname, "\nDestination:", destination, "\nTitle extracted from web:",
                  default)
            fname = default if fname == "" else fname
            temp_destination = str(
                input("Enter destination for downloading:[Current: %s] " % destination))
            temp_fname = str(
                input("Enter file name for downloading:[Current: %s] " % fname))
            destination = destination if temp_destination is "" else temp_destination
            fname = fname if temp_fname is "" else temp_fname
            destination, fname = self.path_handler(
                _os.path.join(destination, fname), default, url, 0)
        elif _os.path.exists(path):
            choice = str(
                input("File already exists, [D]ownload | [R]ename | [S]kip(default) :"))
            if choice == "D":
                print("Downloading")
                return destination, fname
            elif choice == "R":
                rename = 1
                print("Renaming...")
                destination, fname = self.path_handler(
                    _os.path.join(destination, fname), default, url, rename)
            else:
                print("SKIPPING either due to user choice or invalid choice")
                return
        return destination, fname

    def request(self, bytesize: int, url: str, method: str = "GET", attempt: int = 0) -> bool:
        '''Returns false incase the request fails to connect
        '''
        method = self.request_method
        headers = {"Range": "bytes=%d-" %
                   bytesize, "Accept-Encoding": "gzip, deflate, identity, br"}

        self.check_internet()
        try:
            self.content_request = self.session.request(
                method, url, headers=headers, stream=True, timeout=10)
        except _requests.exceptions.ConnectionError as e:
            print("Error encountered:", e)
            self.check_internet()
            print("Internet Connected. Retrying download")
            self.download()
            # Because download() starts the whole process again; handling
            # current process with no response i.e. return false.
            return False
        except (_requests.exceptions.ConnectTimeout, _requests.exceptions.ReadTimeout) as e:
            print("Error encountered:", e)
            self.check_internet()
            print("Internet Connected. Retrying download")
            self.download()
            # Because download() starts the whole process again; handling
            # current process with no response i.e. return false.
            return False

        content_request_status = True
        if self.content_request.status_code == 206 or self.content_request.status_code == 200:
            if ((self.content_request.status_code == 200) and (self.content_request.headers.get("Accept-Ranges") != "bytes")) and bytesize != 0:
                print("This url doesn't have Resume support, restarting download...")
                content_request_status = self.request(0, url)
        else:
            print("\nError code:", self.content_request.status_code)
            if attempt < 5:
                print("Attempt {} of 5".format(attempt + 1))
                i = 0
                while(i < 5):
                    _sys.stdout.write("\rRetrying in, {}".format(5 - i))
                    _sys.stdout.flush()
                    i += 1
                    _time.sleep(1)
                _sys.stdout.write("\rRetrying...    ")
                _sys.stdout.flush()
                content_request_status = self.request(
                    bytesize, url, method, attempt + 1)
            else:
                print("SKIPPING...")  # Bailing out!
                return False
        return content_request_status

    @staticmethod
    def calculate_remaining_time(total_size: int, downloaded_size: int, speed: int) -> str:
        '''Calculates total time remaining for the download to complete.
        To be used in file_handler for UI puposes.
        Can't handle approximately bigger than 15:00:00.
        '''
        total_size = downloaded_size if total_size < downloaded_size else total_size
        if speed != 0:
            try:
                time_remaining = _time.strftime('%H:%M:%S', _time.gmtime(
                    (total_size - downloaded_size) // speed))
            except OSError as e:
                if e.errno == 84:
                    time_remaining = "You really don't wanna know"
        else:
            time_remaining = "00:00:00"
        return "[{}]".format(time_remaining)

    def file_handler(self, path: str, content_request, content_size: int, resume: bool = False) -> None:
        '''Responsible for reading bytes from internet and saving locally.
        '''
        open_param, dl = ("ab", _os.path.getsize(
            path + ".mddownload")) if resume else ("wb+", 0)
        chunk_size, content_size_humanized = (1024, None) if content_size is None else (
            min(int(2 * content_size / 100), 1048576), self.humanize_bytes(content_size))
        i = 0
        with open(path + ".mddownload", open_param) as fh:
            time_start = _time.time()
            speed = 0
            time_diff = 0
            temp_len_dl = 0
            try:
                for data in content_request.raw.stream(chunk_size, decode_content=False):
                    len_dl = len(data)
                    dl += len_dl
                    downloaded_size_humanized = self.humanize_bytes(dl)
                    fh.write(data)
                    time_end = _time.time()

                    # time_diff, temp_len_dl, speed, are all there to stabalize
                    # the 'speed calculated' when chunk_size is too low.
                    temp_len_dl += len_dl
                    time_diff += time_end - time_start

                    if time_diff > 1:
                        speed = temp_len_dl // time_diff
                        temp_len_dl = 0
                        time_diff = 0

                    if content_size is None:
                        _sys.stdout.write("\rDownloading{}   {}   {}ps".format(
                            ("." * i).ljust(4), downloaded_size_humanized.rjust(11), self.humanize_bytes(speed).rjust(13)))
                        chunk_size = max(1024, min(int(dl / 100), 1048576))
                        i = 0 if i > 3 else i + 1
                    else:
                        done = min(int(50 * dl / content_size), 50)
                        _sys.stdout.write("\r[{}{}{}]   {}/{}   {}ps   {}".format("=" * done, ">" * bool(50 - done), "." * (50 - done - 1), downloaded_size_humanized.rjust(
                            13), content_size_humanized if dl < content_size else downloaded_size_humanized, self.humanize_bytes(speed).rjust(13), self.calculate_remaining_time(content_size, dl, speed).ljust(20)))
                    _sys.stdout.flush()
                    time_start = _time.time()
            except (_requests.urllib3.exceptions.ReadTimeoutError, _requests.urllib3.exceptions.ProtocolError)as e:
                print("Error encountered:", e)
                self.check_internet()
                print("Internet Connected. Retrying download")
                self.download()
                # Because download() starts the whole process again; handling
                # current process with no response i.e. return none.
                return None

        self.convert_to_final_file(
            path + ".mddownload", dl, content_request.headers.get("Content-Encoding"))

    def decompress(self, path_of_file, encodings) -> None:
        '''Handles different kinds of decompressions incase the data received is in compressed form.
        '''
        encoding_dict = {"gzip": _gzip.decompress,
                         "deflate": _zlib.decompress,
                         "identity": lambda i: i,
                         "br": _brotli.decompress}
        encodings = encodings.split(",")
        with open(path_of_file, "rb") as fh:
            x = fh.read()
        for encoding in encodings[::-1]:
            x = encoding_dict.get(encoding)(x)
        with open(path_of_file, "wb") as fh:
            fh.write(x)

    def convert_to_final_file(self, path_to_file: str, size: int, content_encoding) -> None:
        '''Responsible for final check of download completion and rename to final file.
        '''
        fsize = _os.path.getsize(path_to_file)
        if fsize == size:
            if content_encoding is not None:
                self.decompress(path_to_file, content_encoding)
            _os.rename(path_to_file, path_to_file[:-11])
            print("\nDownload Complete\nFile stored at:", path_to_file[:-11])
        else:
            print("File size mismatch\nStored file size:", fsize,
                  "\nDownload size:", size, "\nSKIPPING...")

    @staticmethod
    def check_internet() -> None:
        '''Either connect the internet or the scipt calls exit. returns nothing
        '''
        no_intenet = True
        while (no_intenet):

            try:
                _requests.head("http://google.com/generate_204", timeout=4)
                no_intenet = False
            except _requests.exceptions.ConnectionError as e:
                print("No intenet connection")
                no_intenet = True
                retry = str(input("Retry? [Y|N]: "))
                if retry == 'N':
                    _sys.exit("No internet")

    def download(self) -> None:
        '''Main and only intended working method. Initializes the whole process.
        '''

        print("Connecting...")
        print("URL:", self.url)

        content_request_status = self.request(0, self.url)
        if content_request_status is False:
            return
        titleheader = self.content_request.headers.get("Content-Disposition")
        if titleheader is None:
            self.title_fetched = _os.path.split(
                self.url)[-1].split("?")[0].split("#")[0].split("&")[0]
        else:
            re_obj_fname = _re.search(r'filename=.*?["\'];', titleheader)
            if re_obj_fname is not None:
                self.title_fetched = titleheader[
                    re_obj_fname.start() + 10:re_obj_fname.end() - 2]
            else:
                self.title_fetched = _os.path.split(
                    self.url)[-1].split("?")[0].split("#")[0].split("&")[0]

        self.path = self.title_fetched if self.path is None else self.path
        path_tuple = self.path_handler(self.path, self.title_fetched, self.url)

        if path_tuple is None:
            return
        else:
            self.destination, self.fname = path_tuple
        self.path = _os.path.join(self.destination, self.fname)
        print("Title:", self.fname)
        size_header = self.content_request.headers.get("Content-Length")
        if size_header is None:
            self.filesize = None
        else:
            self.filesize = int(size_header)

        if _os.path.exists(self.path + ".mddownload"):
            print("Found incomplete download, resuming...")
            self.local_filesize = _os.path.getsize(self.path + ".mddownload")

            if self.filesize is None or self.filesize > self.local_filesize:
                content_request_status = self.request(
                    self.local_filesize, self.url)
                if content_request_status is False:
                    return
                self.is_resume = True
                self.file_handler(self.path, self.content_request,
                                  self.filesize, resume=self.is_resume)
            elif self.filesize == self.local_filesize:
                self.convert_to_final_file(
                    self.path + ".mddownload", self.filesize, self.content_request.headers.get("Content-Encoding"))
            elif self.filesize < self.local_filesize:
                print("Mismatch in file size", "\nOnline file size:", self.humanize_bytes(self.filesize), "\nOffline file size:",
                      self.humanize_bytes(self.local_filesize), "\nSKIPPING...")
                return
        else:
            if self.filesize is None:
                print("No file size information available. Downloading indefinitely")
            else:
                self.filesize_humanized = self.humanize_bytes(self.filesize)
                print("File size:", self.filesize_humanized)

            self.file_handler(self.path, self.content_request, self.filesize)
