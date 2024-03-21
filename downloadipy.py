import gzip
import os
import sys
import time
import zlib
from email.message import Message

import brotli
import requests
from urllib3.exceptions import ReadTimeoutError, ProtocolError


class Downloader:

    def __init__(self, request_url: str, path: str = None, method: str = "GET", cookies: dict = None,
                 headers: dict = None, skip_existing: bool = False, timeout: int = 10) -> None:
        self.url = request_url
        self.path = path
        self.request_method = method
        self.session_cookies = cookies
        self.is_resume = False
        self.session = requests.Session()
        self.headers = headers
        self.skip = skip_existing
        self.content_request = None
        self.title_fetched = None
        self.filesize = None
        self.local_filesize = None
        self.destination = None
        self.fname = None
        self.byte_start = 0
        self.timeout = timeout

        if self.session_cookies is not None:
            self.session.cookies.update(self.session_cookies)

    @staticmethod
    def humanize_bytes(nbytes: float) -> str:
        """Convert amount of bytes to human-readable form.
        """
        suffix = {0: " B",
                  1: " KB",
                  2: " MB",
                  3: " GB"}
        i = 0
        while (nbytes // 1024 > 0) and (i < 3):
            nbytes = round(nbytes / 1024, 2)
            i += 1
        return str(nbytes) + suffix.get(i)

    def path_handler(self, path: str, default: str):
        """Handle validation of the complete path.
        """
        if os.path.isdir(path):
            destination = path
            fname = ""
        else:
            destination, fname = os.path.split(path)

        if fname == "":
            fname = default

        if destination == "":
            destination = "."

        while not os.path.isdir(destination):
            temp_destination = str(
                input("Destination non-existent:[Current: %s] " % destination))
            if temp_destination != "":
                destination = temp_destination

        if fname == "":
            print("Enter valid file name\nFile name:", fname, "\nDestination:", destination,
                  "\nTitle extracted from web:",
                  default)
            temp_destination = str(
                input("Enter destination for downloading:[Current: %s] " % destination))
            temp_fname = str(
                input("Enter file name for downloading:[Current: %s] " % fname))
            if temp_destination != "":
                destination = temp_destination
            if temp_fname != "":
                fname = temp_fname
            return self.path_handler(
                os.path.join(destination, fname), default)
        elif os.path.exists(os.path.join(destination, fname)):
            print("File already exists")
            if self.skip:
                print("Skipping")
                return
            else:
                print("Overwriting")
                return destination, fname
        return destination, fname

    def request(self, bytesize: int, attempt: int = 0) -> bool:
        """Return false in case the request fails to connect
        """
        method = self.request_method
        headers = {"Range": "bytes=%d-" %
                            bytesize, "Accept-Encoding": "gzip, deflate, identity, br",
                   "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) "
                                 "Chrome/105.0.0.0 Safari/537.36"}
        if self.headers is not None:
            headers.update(self.headers)
        self.check_internet()
        try:
            self.content_request = self.session.request(
                method, self.url, headers=headers, stream=True, timeout=self.timeout)
        except (requests.exceptions.ConnectTimeout, requests.exceptions.ReadTimeout,
                requests.exceptions.ConnectionError) as e:
            print("Error encountered:", e)
            self.check_internet()
            print("Internet Connected. Retrying download")
            self.timeout = min(self.timeout + 5, 60)
            self.download()
            # Because download() starts the whole process again; handling
            # current process with no response i.e. return false.
            return False

        content_request_status = True

        if self.content_request.status_code == 206:
            range_info = self.content_request.headers.get(
                "Content-Range").split(" ")[1]

            byte_range, size = range_info.split("/")

            if byte_range == "*":
                print("Unsatisfiable range",
                      self.content_request.headers.get("Content-Range"))
                self.download()
                return False
            else:
                self.byte_start = int(byte_range.split("-")[0])

            if size == "*":
                self.filesize = None
            else:
                self.filesize = int(size)

        elif self.content_request.status_code == 200:
            self.is_resume = False
            if bytesize != 0:
                print("This url doesn't have Resume support, restarting download...")
                content_request_status = self.request(0)

        else:
            print("\nError code:", self.content_request.status_code)
            if attempt < 5:
                print("Attempt {} of 5".format(attempt + 1))
                i = 0
                while i < 5:
                    sys.stdout.write("\rRetrying in, {}".format(5 - i))
                    sys.stdout.flush()
                    i += 1
                    time.sleep(1)
                sys.stdout.write("\rRetrying...    ")
                sys.stdout.flush()
                content_request_status = self.request(
                    bytesize, attempt + 1)
            else:
                print("SKIPPING...")  # Bailing out!
                return False
        return content_request_status

    @staticmethod
    def calculate_remaining_time(total_size: int, downloaded_size: int, speed: float) -> str:
        """Calculates total time remaining for the download to complete.
        To be used in file_handler for UI purposes.
        Can't handle approximately bigger than 15:00:00.
        """
        if total_size < downloaded_size:
            time_remaining = "00:00:00"
        elif speed != 0:
            try:
                time_remaining = time.strftime("%H:%M:%S", time.gmtime(
                    (total_size - downloaded_size) // speed))
            except OSError as e:
                if e.errno == 84:
                    time_remaining = "??:??:??"
                else:
                    raise e
        else:
            time_remaining = "00:00:00"
        return "[{}]".format(time_remaining)

    def file_handler(self, path: str, content_request, content_size, resume: bool = False) -> None:
        """Read bytes from internet and save locally.
        """
        open_param, dl = ("rb+", os.path.getsize(
            path + ".mddownload")) if resume else ("wb+", 0)
        chunk_size = 1048576  # 1024*1024 = 1048576(1MB)
        content_size_humanized = None if content_size is None else self.humanize_bytes(
            content_size)
        with open(path + ".mddownload", open_param) as fh:
            fh.seek(0, 2)
            fh_pos = fh.tell()
            i = 0

            if fh_pos >= self.byte_start:
                fh.seek(self.byte_start, 0)
            else:
                content_request_status = self.request(fh_pos)
                if content_request_status is False:
                    return None
                else:
                    content_request = self.content_request

            time_start = time.time()
            try:
                for data in content_request.raw.stream(chunk_size, decode_content=False):
                    len_dl = len(data)
                    dl += len_dl
                    downloaded_size_humanized = self.humanize_bytes(dl)
                    fh.write(data)
                    time_end = time.time()
                    time_end = time_end if time_end - time_start > 0.1 else time_end + 0.1

                    speed = len_dl // (time_end - time_start)
                    if content_size is None:
                        sys.stdout.write("\rDownloading{:<4} {:>10} {:>10}ps".format(
                            ("." * i), downloaded_size_humanized, self.humanize_bytes(speed)))
                        i = 0 if i > 3 else i + 1
                    else:
                        done = min(int(50 * dl / content_size), 50)
                        sys.stdout.write(
                            "\r[{}{}{}] {:>10}/{:<10} {:>10}ps {}".format("=" * done, ">" * bool(50 - done),
                                                                          "." * (50 - done - 1),
                                                                          downloaded_size_humanized,
                                                                          content_size_humanized if dl < content_size
                                                                          else downloaded_size_humanized,
                                                                          self.humanize_bytes(speed),
                                                                          self.calculate_remaining_time(content_size,
                                                                                                        dl, speed)))
                    sys.stdout.flush()
                    time_start = time.time()
            except (ReadTimeoutError, ProtocolError) as e:
                print("Error encountered:", e)
                self.check_internet()
                print("Internet Connected. Retrying download")
                self.timeout = min(self.timeout + 5, 60)
                self.download()
                # Because download() starts the whole process again; handling
                # current process with no response i.e. return none.
                return None

        if content_size == dl or content_size is None:
            self.convert_to_final_file(
                path + ".mddownload", dl, content_request.headers.get("Content-Encoding"))
        else:
            print("Unexpected connection termination. Attempting resume...")
            self.check_internet()
            print("Internet Connected. Retrying download")
            self.download()
            # Because download() starts the whole process again; handling
            # current process with no response i.e. return none.
            return None

    @staticmethod
    def decompress(path_of_file, encodings) -> None:
        """Handle different kinds of decompression in case the data received is in compressed form.
        """
        encoding_dict = {"gzip": gzip.decompress,
                         "deflate": zlib.decompress,
                         "identity": lambda i: i,  # No transformation
                         "br": brotli.decompress}
        encodings = encodings.split(",")
        with open(path_of_file, "rb") as fh:
            x = fh.read()
        for encoding in encodings[::-1]:
            x = encoding_dict.get(encoding)(x)
        with open(path_of_file, "wb") as fh:
            fh.write(x)

    def convert_to_final_file(self, path_to_file: str, size: int, content_encoding) -> None:
        """Check download completion and rename to final file.
        """
        fsize = os.path.getsize(path_to_file)
        if fsize == size:
            if content_encoding is not None:
                self.decompress(path_to_file, content_encoding)
            try:
                os.rename(path_to_file, path_to_file[:-11])
            except OSError as e:
                if e.errno == 5:
                    print(
                        "Another process is accessing file, stop the process and rerun the software", e)
                    return
                else:
                    raise e
            print("\nDownload Complete\nFile stored at:", path_to_file[:-11])
        else:
            print("File size mismatch\nStored file size:", fsize,
                  "\nDownload size:", size, "\nSKIPPING...")

    @staticmethod
    def check_internet() -> None:
        """Return nothing
        """
        no_internet = True
        timeout = 10
        while no_internet:

            try:
                requests.head("http://google.com/generate_204", timeout=timeout)
                no_internet = False
            except (requests.exceptions.ConnectionError, requests.exceptions.ReadTimeout):
                print("No internet connection")
                no_internet = True
                retry = str(input("Retry? [Y|N]: "))
                if retry == "N":
                    sys.exit("No internet")
                timeout = min(timeout + 5, 60)

    def download(self) -> None:
        """Initialize the whole process
        """

        print("Connecting...")
        print("URL:", self.url)

        content_request_status = self.request(0)
        if content_request_status is False:
            return

        self.title_fetched = os.path.split(
            self.url)[-1].split("?")[0].split("#")[0].split("&")[0]

        titleheader = self.content_request.headers.get("Content-Disposition")
        if titleheader is not None:
            titleheader_parsed = Message()
            titleheader_parsed['Content-Disposition'] = titleheader
            if titleheader_parsed.get_content_disposition() == "attachment":
                temp_title = titleheader_parsed.get_filename()
                if temp_title is not None:
                    self.title_fetched = temp_title

        if self.path is None:
            self.path = self.title_fetched
        path_tuple = self.path_handler(self.path, self.title_fetched)

        if path_tuple is None:
            return
        else:
            self.destination, self.fname = path_tuple
        self.path = os.path.join(self.destination, self.fname)
        print("Title:", self.fname)
        size_header = self.content_request.headers.get("Content-Length")
        self.filesize = None if size_header is None else int(size_header)

        if os.path.exists(self.path + ".mddownload"):
            print("Found incomplete download, resuming...")
            self.local_filesize = os.path.getsize(self.path + ".mddownload")

            if self.filesize is None or self.filesize > self.local_filesize:
                self.is_resume = True
                content_request_status = self.request(
                    self.local_filesize)
                if content_request_status is False:
                    return

                self.file_handler(self.path, self.content_request,
                                  self.filesize, resume=self.is_resume)
            elif self.filesize == self.local_filesize:
                self.convert_to_final_file(
                    self.path + ".mddownload", self.filesize, self.content_request.headers.get("Content-Encoding"))
            elif self.filesize < self.local_filesize:
                print("Mismatch in file size", "\nOnline file size:", self.humanize_bytes(self.filesize),
                      "\nOffline file size:",
                      self.humanize_bytes(self.local_filesize), "\nSKIPPING...")
                return
        else:
            if self.filesize is None:
                print("No file size information available. Downloading indefinitely")
            else:
                filesize_humanized = self.humanize_bytes(self.filesize)
                print("File size:", filesize_humanized)

            self.file_handler(self.path, self.content_request, self.filesize)


if __name__ == "__main__":
    url = str(input("URL: "))
    location = str(input("Location: "))
    down_obj = Downloader(url, location, skip_existing=True)
    down_obj.download()
