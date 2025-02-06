import os
import re
import requests
import base64
from typing import Dict, List, Tuple
from urllib.parse import urlparse

class GitHubRepoAnalyzer:
    def __init__(self, token: str, repo_url: str):
        self.headers = {'Authorization': f'token {token}'}
        self.owner, self.repo = self._parse_github_url(repo_url)
        self.base_url = f'https://api.github.com/repos/{self.owner}/{self.repo}'
        self.content_cache: Dict[str, str] = {}

    def _parse_github_url(self, url: str) -> Tuple[str, str]:
        patterns = [
            r'github\.com[:/]([^/]+)/([^/\.]+)(?:\.git)?$',  # Handles HTTPS and SSH URLs
            r'github\.com/([^/]+)/([^/]+)/?$'  # Handles web URLs
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
        content = base64.b64decode(response.json()['content']).decode('utf-8')
        self.content_cache[file_api_url] = content
        return content

    def analyze_repo(self) -> Tuple[List[str], Dict[str, str]]:
        structure = []
        contents = {}

        def process_path(path: str, prefix: str = ''):
            items = self.get_contents(path)
            for item in sorted(items, key=lambda x: (x['type'] != 'dir', x['name'])):
                full_path = f"{path}/{item['name']}" if path else item['name']
                structure_path = f"{prefix}{'├── ' if prefix else ''}{item['name']}"
                if item['type'] == 'dir':
                    structure.append(structure_path)
                    process_path(full_path, prefix + '│   ')
                else:
                    structure.append(structure_path)
                    try:
                        contents[full_path] = self.get_file_content(item['url'])
                    except Exception as e:
                        contents[full_path] = f"Error reading file: {str(e)}"

        process_path('')
        return structure, contents

def save_analysis(structure: List[str], contents: Dict[str, str], output_file: str):
    with open(output_file, 'w', encoding='utf-8') as f:
        f.write('\n'.join(structure) + '\n\n')
        # Improved file content header for clarity
        for path, content in contents.items():
            f.write('---\n')
            f.write(f'File: {path}\n')
            f.write('---\n')
            f.write(content)
            f.write('\n\n')

def main():
    token = os.getenv('GITHUB_TOKEN')
    if not token:
        print("Error: GITHUB_TOKEN environment variable is not set")
        return
    repo_url = input('GitHub repository URL: ')
    analyzer = GitHubRepoAnalyzer(token, repo_url)
    output_file = f"{analyzer.repo}.txt"
    try:
        structure, contents = analyzer.analyze_repo()
        save_analysis(structure, contents, output_file)
        print(f"\nAnalysis completed successfully. Results saved to {output_file}")
    except Exception as e:
        print(f"Error: {str(e)}")

if __name__ == '__main__':
    main()
