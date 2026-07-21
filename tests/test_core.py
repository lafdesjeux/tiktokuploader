import unittest

from tiktok_desktop_publisher.api import MAX_CHUNK, build_chunk_plan, utf16_length


class ChunkPlanTests(unittest.TestCase):
    def test_small_video_is_one_chunk(self):
        plan = build_chunk_plan(4 * 1024 * 1024)
        self.assertEqual(plan.total_chunk_count, 1)
        self.assertEqual(plan.chunk_lengths, (4 * 1024 * 1024,))

    def test_medium_video_is_one_chunk(self):
        plan = build_chunk_plan(40 * 1024 * 1024)
        self.assertEqual(plan.total_chunk_count, 1)

    def test_large_video_uses_multiple_chunks_and_merges_remainder(self):
        size = 50_000_123
        plan = build_chunk_plan(size, 10_000_000)
        self.assertEqual(plan.total_chunk_count, 1)  # file is below 64 MiB

        size = MAX_CHUNK + 12_345_678
        plan = build_chunk_plan(size, 16 * 1024 * 1024)
        self.assertGreaterEqual(plan.total_chunk_count, 2)
        self.assertEqual(sum(plan.chunk_lengths), size)
        self.assertGreaterEqual(plan.chunk_lengths[-1], plan.chunk_size)

    def test_utf16_count(self):
        self.assertEqual(utf16_length("abc"), 3)
        self.assertEqual(utf16_length("😀"), 2)


if __name__ == "__main__":
    unittest.main()
