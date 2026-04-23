from core.interfaces import EditManifest

from .base_processor import BaseProcessor


class AudioDenoiserFilter(BaseProcessor):
    """Add render-time FFmpeg `afftdn` filters for enabled tracks."""

    def process(
        self,
        manifest: EditManifest,
        host_audio,
        guest_audio,
        detection_results,
    ) -> EditManifest:
        """Append stationary denoise filters based on config flags."""
        # host_audio, guest_audio, and detection_results are intentionally unused.
        if self.config.get("noise_reduction_host"):
            # afftdn has no 'mode' option; defaults to white-noise (stationary) reduction
            manifest.add_host_filter("afftdn")

        if self.config.get("noise_reduction_guest"):
            manifest.add_guest_filter("afftdn")

        return manifest

    def get_name(self) -> str:
        return "AudioDenoiserFilter"
