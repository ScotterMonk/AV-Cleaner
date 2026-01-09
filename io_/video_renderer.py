# io/video_renderer.py

import ffmpeg
from utils.logger import get_logger

logger = get_logger(__name__)

def render_project(host_path, guest_path, manifest, out_host, out_guest, config):
    """
    Constructs and executes the FFmpeg graph.
    Cuts video and audio simultaneously to guarantee sync.
    """
    
    def build_chain(input_path, filters, keep_segments):
        inp = ffmpeg.input(input_path)
        v = inp.video
        a = inp.audio
        
        # 1. Apply Audio Filters (Normalization, etc.)
        for f in filters:
            a = a.filter(f.filter_name, **f.params)
            
        # 2. Apply Cutting (Trimming)
        if keep_segments:
            segments_v = []
            segments_a = []
            for start, end in keep_segments:
                # Video Trim (Reset PTS to start at 0 relative to segment)
                seg_v = v.trim(start=start, end=end).setpts('PTS-STARTPTS')
                segments_v.append(seg_v)
                
                # Audio Trim (Must match exactly)
                seg_a = a.filter_('atrim', start=start, end=end).filter_('asetpts', 'PTS-STARTPTS')
                segments_a.append(seg_a)
                
            # Concatenate all segments
            v = ffmpeg.concat(*segments_v, v=1, a=0).node[0]
            a = ffmpeg.concat(*segments_a, v=0, a=1).node[0]
            
        return v, a

    if not out_host and not out_guest:
        raise ValueError("render_project() requires at least one output (out_host or out_guest)")

    # Build graphs (only for requested outputs)
    h_v = h_a = None
    g_v = g_a = None
    if out_host:
        h_v, h_a = build_chain(host_path, manifest.host_filters, manifest.keep_segments)
    if out_guest:
        g_v, g_a = build_chain(guest_path, manifest.guest_filters, manifest.keep_segments)
    
    # Common Output Settings
    enc_opts = {
        'vcodec': config['video_codec'],
        'preset': config['video_preset'],
        'crf': config['crf'],
        'acodec': config['audio_codec'],
        'audio_bitrate': config['audio_bitrate']
    }
    
    # Define Outputs
    # Note: Running sequentially is safer for memory, though parallel is possible
    if out_host:
        logger.info("Rendering Host Video...")
        ffmpeg.output(h_v, h_a, out_host, **enc_opts).run(overwrite_output=True)

    if out_guest:
        logger.info("Rendering Guest Video...")
        ffmpeg.output(g_v, g_a, out_guest, **enc_opts).run(overwrite_output=True)
