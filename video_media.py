"""Bounded MP4/MOV decoding into private, metadata-free playback derivatives."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import threading

import video_policy

_workers = threading.BoundedSemaphore(2)


class VideoUnavailable(Exception):
    pass


def executable(name):
    configured = os.environ.get('MOMIQ_'+name.upper())
    local = Path(__file__).parent/'.local/toolchains/ffmpeg-9.0.2/ffmpeg-9.0.2-essentials_build/bin'/f'{name}.exe'
    found = configured or (str(local) if os.name == 'nt' and local.is_file() else shutil.which(name))
    if not found or not Path(found).is_file():
        raise VideoUnavailable('Video qayta ishlash xizmati hozir mavjud emas')
    return found


def available():
    try:
        executable('ffmpeg'); executable('ffprobe')
        return True
    except VideoUnavailable:
        return False


def run(name, args, timeout=15):
    try:
        result = subprocess.run([executable(name), '-v', 'error', '-max_alloc', '67108864', *args],
                                stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                                timeout=timeout, creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0)
    except subprocess.TimeoutExpired as error:
        raise ValueError('Videoni qayta ishlash vaqti tugadi; kichikroq video tanlang') from error
    if result.returncode or len(result.stdout) > 32768:
        raise ValueError('Video ochilmadi yoki buzilgan; MP4/MOV video tanlang')
    return result.stdout


def probe(path):
    raw = run('ffprobe', ['-protocol_whitelist', 'file', '-f', 'mov', '-enable_drefs', '0',
                         '-use_absolute_path', '0', '-i', str(path), '-show_entries',
                         'stream=codec_type,codec_name,width,height,duration,avg_frame_rate:format=format_name,duration', '-of', 'json'])
    try:
        data = json.loads(raw)
        streams = [s for s in data['streams'] if s['codec_type'] == 'video']
        if len(streams) != 1: raise ValueError('Bitta video oqimi kerak')
        stream = streams[0]
        if stream['codec_name'] not in ('h264', 'hevc'):
            raise ValueError('H.264 yoki HEVC video tanlang')
        width, height = stream['width'], stream['height']
        if not (16 <= width <= 1920 and 16 <= height <= 1920 and width*height <= 1920*1080):
            raise ValueError('Video 1080p dan katta bo‘lmasin')
        numerator, denominator = map(int, stream['avg_frame_rate'].split('/'))
        if denominator <= 0 or not 0 < numerator/denominator <= 60:
            raise ValueError('Video tezligi 60 fps dan oshmasin')
        duration = video_policy.duration_ms(stream.get('duration', data.get('format', {}).get('duration')))
        return {'durationMs':duration, 'width':width, 'height':height}
    except (KeyError, TypeError, ZeroDivisionError, json.JSONDecodeError) as error:
        raise ValueError('Video metadata aniqlanmadi') from error


def sha256(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def prepare(source, directory):
    """Decode the entire bounded source, retaining audio and stripping metadata."""
    source, directory = Path(source), Path(directory)
    if not 12 <= source.stat().st_size <= video_policy.MAX_BYTES:
        raise ValueError('Video 32 MiB dan kichik bo‘lishi kerak')
    with source.open('rb') as stream:
        if stream.read(12)[4:8] != b'ftyp': raise ValueError('MP4/MOV video tanlang')
    if not _workers.acquire(blocking=False):
        raise VideoUnavailable('Video xizmati band. Birozdan so‘ng qayta urining')
    try:
        measured = probe(source)
        output, poster = directory/'playback.mp4', directory/'poster.jpg'
        run('ffmpeg', ['-nostdin', '-xerror', '-err_detect', 'explode', '-protocol_whitelist', 'file',
            '-f', 'mov', '-enable_drefs', '0', '-use_absolute_path', '0', '-i', str(source),
            '-map', '0:v:0', '-map', '0:a:0?', '-map_metadata', '-1', '-map_chapters', '-1',
            '-vf', "scale='min(1280,iw)':'min(1280,ih)':force_original_aspect_ratio=decrease:force_divisible_by=2,fps=24",
            '-c:v', 'libx264', '-preset', 'veryfast', '-crf', '28', '-pix_fmt', 'yuv420p',
            '-c:a', 'aac', '-b:a', '96k', '-threads', '2', '-t', '61', '-fs', str(video_policy.MAX_BYTES),
            '-movflags', '+faststart', '-y', str(output)], timeout=90)
        result = probe(output)
        if output.stat().st_size >= video_policy.MAX_BYTES or abs(result['durationMs']-measured['durationMs']) > 150:
            raise ValueError('Video to‘liq qayta ishlanmadi; boshqa video tanlang')
        run('ffmpeg', ['-nostdin', '-protocol_whitelist', 'file', '-i', str(output),
                       '-frames:v', '1', '-vf', 'scale=480:480:force_original_aspect_ratio=decrease',
                       '-map_metadata', '-1', '-threads', '1', '-y', str(poster)], timeout=15)
        result.update(sourceHash=sha256(source), videoHash=sha256(output), posterHash=sha256(poster),
                      bytes=output.stat().st_size, videoFile=output, posterFile=poster)
        return result
    finally:
        _workers.release()
