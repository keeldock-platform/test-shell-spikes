"""Ubuntu gates must provision media before consuming it."""
from pathlib import Path
import re
import unittest

ROOT = Path(__file__).resolve().parents[2]


class MediaGateTests(unittest.TestCase):
    def test_each_gate_installs_before_consuming_media(self):
        workflow = (ROOT / '.github/workflows/shell-spikes.yml').read_text()
        for job, consumer in [('public-static', 'Check case deadlines and immutable evidence snapshots'),
                              ('collect', 'Produce result matrix and hashes'),
                              ('android', 'Select hosted Android SDK tools and enable KVM')]:
            block = workflow.split(f'\n  {job}:\n', 1)[1]
            # Next job starts at exactly two spaces; nested keys must stay in the block.
            block = re.split(r'\n  [a-z][a-z-]*:\n', block, maxsplit=1)[0]
            self.assertEqual(block.count('run: bash ci/install-media-validator.sh'), 1, job)
            self.assertLess(block.index('run: bash ci/install-media-validator.sh'), block.index(consumer), job)
        self.assertIn("python -m unittest discover -s ci/tests -p 'test_round*.py'", workflow)

    def test_installer_is_pinned_authenticated_and_never_trusts_path_presence(self):
        source = (ROOT / 'ci/install-media-validator.sh').read_text()
        self.assertNotIn('if ! command -v', source)
        for required in ['ffmpeg=$media_version', 'media_version=\'7:6.1.1-3ubuntu5\'',
                         'sha256sum --check --strict', 'Dir::Etc::sourceparts=-',
                         'signed-by=/usr/share/keyrings/ubuntu-archive-keyring.gpg',
                         'dpkg --verify ffmpeg', '== /usr/bin/ffmpeg', '== /usr/bin/ffprobe',
                         '-c:v libx264', '-show_streams']:
            self.assertIn(required, source)
        self.assertNotIn('snapshot.ubuntu', source)
        self.assertNotIn('ci/apt-host.sh', source)


if __name__ == '__main__':
    unittest.main()
