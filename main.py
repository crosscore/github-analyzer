import os
import re
import requests
import base64
from typing import Dict, List, Tuple

class GitHubRepoAnalyzer:
    def __init__(self, token: str, repo_url: str):
        self.headers = {'Authorization': f'token {token}'}
        self.owner, self.repo = self._parse_github_url(repo_url)
        self.base_url = f'https://api.github.com/repos/{self.owner}/{self.repo}'
        self.content_cache: Dict[str, str] = {}

    def _parse_github_url(self, url: str) -> Tuple[str, str]:
        patterns = [
            r'github\.com[:/]([^/]+)/([^/\.]+)(?:\.git)?$',  # HTTPS/SSH URL
            r'github\.com/([^/]+)/([^/]+)/?$'  # Web URL
        ]
        for pattern in patterns:
            match = re.search(pattern, url)
            if match:
                return match.groups()
        raise ValueError(
            "Invalid GitHub URL. Expected format: "
            "https://github.com/owner/repo or "
            "git@github.com:owner/repo.git"
        )

    def get_contents(self, path: str = '') -> List[Dict]:
        response = requests.get(f'{self.base_url}/contents/{path}', headers=self.headers)
        response.raise_for_status()
        return response.json()

    def get_file_content(self, file_api_url: str) -> str:
        if file_api_url in self.content_cache:
            return self.content_cache[file_api_url]
        response = requests.get(file_api_url, headers=self.headers)
        response.raise_for_status()
        json_resp = response.json()
        if 'content' not in json_resp:
            self.content_cache[file_api_url] = "Non-text content or unexpected format."
            return self.content_cache[file_api_url]
        try:
            content = base64.b64decode(json_resp['content']).decode('utf-8')
        except Exception:
            content = "Error decoding content (possibly binary file)."
        self.content_cache[file_api_url] = content
        return content

    def analyze_repo(self) -> Tuple[List[str], Dict[str, str]]:
        structure = []
        contents = {}

        def process_path(path: str, prefix: str = ''):
            items = self.get_contents(path)
            items = sorted(items, key=lambda x: (x['type'] != 'dir', x['name']))
            count = len(items)
            for idx, item in enumerate(items):
                connector = '└── ' if idx == count - 1 else '├── '
                full_path = f"{path}/{item['name']}" if path else item['name']
                structure_path = f"{prefix}{connector}{item['name']}"
                structure.append(structure_path)
                if item['type'] == 'dir':
                    new_prefix = prefix + ('    ' if idx == count - 1 else '│   ')
                    process_path(full_path, new_prefix)
                else:
                    try:
                        contents[full_path] = self.get_file_content(item['url'])
                    except Exception as e:
                        contents[full_path] = f"Error reading file: {str(e)}"

        process_path('')
        return structure, contents

def save_analysis(structure: List[str], contents: Dict[str, str], output_file: str):
    with open(output_file, 'w', encoding='utf-8') as f:
        f.write("# Repository Structure\n\n")
        f.write("```\n")
        f.write("\n".join(structure))
        f.write("\n```\n\n")
        f.write("# File Contents\n\n")
        for path, content in contents.items():
            f.write(f"## {path}\n\n")
            f.write("```\n")
            f.write(content)
            f.write("\n```\n\n")

def main():
    token = os.getenv('GITHUB_TOKEN')
    if not token:
        print("Error: GITHUB_TOKEN environment variable is not set")
        return
    repo_url = input('GitHub repository URL: ')
    analyzer = GitHubRepoAnalyzer(token, repo_url)
    output_file = f"{analyzer.repo}.md"
    try:
        structure, contents = analyzer.analyze_repo()
        save_analysis(structure, contents, output_file)
        # Get absolute path for output_file and display it.
        full_output_path = os.path.abspath(output_file)
        print(f"\nAnalysis completed successfully. Results saved to:\n{full_output_path}")
    except Exception as e:
        print(f"Error: {str(e)}")

if __name__ == '__main__':
    main()
