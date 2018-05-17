import os
import time
import errno
import fnmatch
import subprocess as sp
import tempfile
from math import sqrt
from itertools import repeat, chain
from contextlib import contextmanager

import pytest


def pytest_addoption(parser):
    group = parser.getgroup('xvfb_recorder', 'xvfb recorder')
    group.addoption(
        '--xvfb',
        action='store_true',
        help='run Xvfb for tests'
    )
    group.addoption(
        '--xvfb-recording',
        help='record tests run (all | none | failed) using ffmpeg; '
             'if set --xvfb also required',
        choices=['all', 'none', 'failed'],
        default='none'
    )
    group.addoption(
        '--no-mosaic-filter',
        action='store_true',
        help='turn off mosaic filter if recording tests with multiple browsers'
    )


def pytest_generate_tests(metafunc):
    recording = metafunc.config.getoption('--xvfb-recording') != 'none'
    if metafunc.config.getoption('--xvfb') and recording:
        metafunc.fixturenames.append('record_xvfb')


@pytest.hookimpl(tryfirst=True, hookwrapper=True)
def pytest_runtest_makereport(item):
    outcome = yield
    rep = outcome.get_result()
    setattr(item, rep.when + '_xvfb_recorder', rep)


@pytest.fixture(scope='session')
def _xvfb_set(request):
    if request.config.getoption('--xvfb'):
        # assert Xvfb is available on PATH and is executable
        if any(os.access(os.path.join(path, 'Xvfb'), os.X_OK)
               for path in os.environ['PATH'].split(os.pathsep)):
            return True
        else:
            raise EnvironmentError('Xvfb executable not found.')
    else:
        return False


@pytest.fixture(scope='session')
def _recording_option(request, _xvfb_set):
    recording = request.config.getoption('--xvfb-recording')
    if recording != 'none':
        if _xvfb_set:
            # assert ffmpeg is available on PATH and is executable
            if not any(os.access(os.path.join(path, 'ffmpeg'), os.X_OK)
                       for path in os.environ['PATH'].split(os.pathsep)):
                raise EnvironmentError('ffmpeg executable not found.')
        else:
            raise pytest.UsageError('--xvfb-recording requires --xvfb')

    return recording


@pytest.fixture(scope='session')
def mosaic_filter(request):
    return not request.config.getoption('--no-mosaic-filter')


@pytest.fixture(scope='module')
def screen_width():
    return 1280


@pytest.fixture(scope='module')
def screen_height():
    return 1024


@pytest.fixture(scope='module')
def screen_depth():
    return 24


@pytest.fixture(scope='module')
def screens():
    return [0]


@pytest.fixture(scope='module')
def movie_dir():
    return './movies'


@pytest.fixture(scope='module')
def xvfb(_xvfb_set, screens, screen_width, screen_height, screen_depth):
    if _xvfb_set:
        display = _find_free_display()
        cmd = _create_xvfb_cmd(display, screens, screen_width,
                               screen_height, screen_depth)
        with open(os.devnull, 'w') as dev_null:
            proc = sp.Popen(cmd, stdout=dev_null, stderr=dev_null,
                            close_fds=True)

        # let Xvfb start
        time.sleep(0.1)
        if proc.poll() is not None:
            raise RuntimeError('Xvfb did not start')

        try:
            yield [':{}.{}'.format(display, screen) for screen in screens]
        finally:
            with suppress(IOError, errnos=(errno.EINVAL, errno.EPIPE)):
                proc.terminate()
                proc.wait()
    else:
        yield [os.environ.get('DISPLAY', None)]


def _find_free_display(min_display_num=1005):
    tmp_dir = tempfile.gettempdir()
    lock_files = fnmatch.filter(os.listdir(tmp_dir), '.X*-lock')
    displays_in_use = (int(name.split('X')[1].split('-')[0])
                       for name in lock_files
                       if os.path.isfile(os.path.join(tmp_dir, name)))
    return max(chain([min_display_num], displays_in_use)) + 1


def _create_xvfb_cmd(display, screens_ids, width, height, depth):
    cmd = ['Xvfb', '-br', '-nolisten', 'tcp',
           ':{display}'.format(display=display)]

    whd = '{width}x{height}x{depth}'.format(width=width,
                                            height=height,
                                            depth=depth)
    for screen_id in screens_ids:
        cmd.extend(['-screen', str(screen_id), whd])
    return cmd


@pytest.fixture(scope='function')
def record_xvfb(request, _recording_option, xvfb, movie_dir, mosaic_filter,
                screen_width, screen_height):
    if not os.path.exists(movie_dir):
        os.makedirs(movie_dir)

    cmd, paths = _create_ffmpeg_cmd(xvfb, screen_width, screen_height,
                                    movie_dir, request.node.name,
                                    mosaic_filter)
    for path in paths:
        with suppress(OSError, errnos=(errno.ENOENT, errno.ENAMETOOLONG)):
            os.remove(path)

    with open(os.devnull, 'w') as dev_null:
        proc = sp.Popen(cmd, stdin=sp.PIPE, stdout=dev_null,
                        stderr=dev_null, close_fds=True)

    # let ffmpeg start
    time.sleep(0.5)
    if proc.poll() is not None:
        raise RuntimeError('ffmpeg did not start')
    request.node._movies = paths

    try:
        yield
    finally:
        with suppress(IOError, errnos=(errno.EINVAL, errno.EPIPE)):
            proc.communicate(input=b'q')
            if not proc.stdin.closed:
                proc.stdin.close()

        test_passed = request.node.setup_xvfb_recorder.passed and request.node.call_xvfb_recorder.passed
        if _recording_option == 'failed' and test_passed:
            for path in paths:
                with suppress(OSError, errnos=(errno.ENOENT, errno.ENAMETOOLONG)):
                    os.remove(path)


def _create_ffmpeg_cmd(displays, width, height, dir_path, file_name,
                       mosaic_filter, qp=1):
    cmd = ['ffmpeg']

    wh = '{width}x{height}'.format(width=width, height=height)
    for display in displays:
        cmd.extend(['-framerate', '25', '-video_size', wh, '-f', 'x11grab',
                    '-i', '{display}'.format(display=display)])

    paths = []
    file_path = os.path.join(dir_path, file_name + '{}.mp4')
    output_fmt = ['-c:v', 'libx264', '-qp', str(qp), '-preset', 'ultrafast']

    display_num = len(displays)
    if display_num > 1:
        cmd.append('-filter_complex')
        if mosaic_filter:
            cmd.append(_create_mosaic_filter(displays, width, height))
        else:
            tagged_streams, tags = _tag_streams(display_num)
            cmd.append(tagged_streams)
            for tag in tags:
                tag = '[{tag}]'.format(tag=tag)
                path = file_path.format(tag)
                paths.append(path)
                cmd.extend(output_fmt + ['-map', tag, path])

    if display_num == 1 or mosaic_filter:
        path = file_path.format('')
        cmd.extend(output_fmt + [path])
        paths.append(path)

    return cmd, paths


def _create_mosaic_filter(displays, width, height):
    filter_fmt = 'nullsrc=size={width}x{height} [{base}]; {stream};{overlay}'
    available_screens = _gen_offsets(len(displays), width, height)
    full_width, full_height = next(available_screens)
    tagged_streams, tags = _tag_streams(len(displays))
    overlaid_streams, base = _overlay_streams(tags, available_screens)
    return filter_fmt.format(width=full_width, height=full_height,
                             base=base, stream=tagged_streams,
                             overlay=overlaid_streams)


def _overlay_streams(tags, offsets):
    overlay_fmt = '[{base}][{tag}] overlay=shortest=1:x={x}:y={y} [{new_base}]'
    last_overlay_fmt = '[{base}][{tag}] overlay=shortest=1:x={x}:y={y}'
    base_fmt = 'base{num}'

    formats = chain(repeat(overlay_fmt, len(tags) - 1), [last_overlay_fmt])
    bases = ((base_fmt.format(num=num), base_fmt.format(num=num+1))
             for num in xrange(len(tags)))
    offsets = iter(offsets)

    return (';'.join(fmt.format(base=base, tag=tag, x=x, y=y,
                                new_base=new_base)
                     for fmt, tag, (x, y), (base, new_base)
                     in zip(formats, tags, offsets, bases)),
            base_fmt.format(num=0))


def _tag_streams(input_streams_num):
    tags = ['v{num}'.format(num=num) for num in xrange(input_streams_num)]
    fmt = '[{stream}:v] setpts=PTS-STARTPTS [{tag}]'
    tagged_streams = ';'.join(fmt.format(stream=i, tag=tag)
                              for i, tag in enumerate(tags))
    return tagged_streams, tags


def _gen_offsets(screen_num, width, height):
    a = b = int(round(sqrt(screen_num)))
    if a*b < screen_num:
        a += 1
    yield int(a*width), int(b*height)
    for i in xrange(a):
        for j in xrange(b):
            yield int(i*width), int(j*height)


@contextmanager
def suppress(exception, errnos):
    try:
        yield
    except exception as e:
        if errno and e.errno not in errnos:
            raise
