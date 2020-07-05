import setuptools


def main():
    setuptools.setup(
        name="downloadipy",
        version="0.1.4",
        description="Internet downloader",
        long_description="Internet downloader with resume support",
        url="https://github.com/avasid/downloadiPy",
        author="Aakif Vasid",
        author_email="vasidaakif@gmail.com",
        license="MIT",
        install_requires=['requests', 'brotli'],
        py_modules=["downloadipy"],
        entry_points="""
            [console_scripts]
            downloadipy = downloadipy:downloadipy
        """
    )


if __name__ == "__main__":
    main()
