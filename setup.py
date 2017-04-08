from setuptools import setup


setup(
    name='pytest-xvfb-recorder',
    version='0.1.0',
    description='pytest plugin allowing starting and recording xvfb session using ffmpeg',
    long_description=open('README.rst').read(),
    author='bwalkowi',
    url='https://github.com/bwalkowi/pytest-xvfb-recorder',
    py_modules=['pytest_xvfb_recorder'],
    install_requires=['pytest>=2.7.3'],
    entry_points={
        'pytest11': [
            'xvfb_recorder = pytest_xvfb_recorder'
        ],
    },
    license='MIT',
    keywords='py.test pytest xvfb recorder automation',
    classifiers=[
        'Development Status :: 3 - Alpha',
        'License :: OSI Approved :: MIT License',
        'Framework :: Pytest',
        'Intended Audience :: Developers',
        'Operating System :: POSIX',
        'Programming Language :: Python',
        'Programming Language :: Python :: 2.7',
        'Programming Language :: Python :: 3.3',
        'Programming Language :: Python :: 3.4',
        'Programming Language :: Python :: 3.5',
        'Programming Language :: Python :: 3.6',
        'Programming Language :: Python :: Implementation :: CPython',
    ]
)
