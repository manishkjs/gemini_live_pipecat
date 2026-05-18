import unittest
import sys
import os

# Add parent directory to path so we can import tools
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from tools.projects import search_projects

class TestProjectSearch(unittest.TestCase):
    def test_search_by_noida(self):
        results = search_projects(query="Noida")
        # Substring match will match Noida and Greater Noida, so all three are returned
        self.assertIn("Gulshan Dynasty", results)
        self.assertIn("ATS Kingston Heath", results)
        self.assertIn("Gaur Aero Suites", results)

    def test_search_by_specific_keyword(self):
        results = search_projects(query="Yamuna")
        self.assertIn("Gaur Aero Suites", results)
        self.assertNotIn("Gulshan Dynasty", results)
        self.assertNotIn("ATS Kingston Heath", results)

    def test_search_no_results(self):
        results = search_projects(query="Mumbai")
        self.assertEqual(results, "No projects found matching your preferences.")

if __name__ == "__main__":
    unittest.main()
