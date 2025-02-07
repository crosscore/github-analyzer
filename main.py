import os
import re
import json
import requests
import base64
from typing import Dict, List, Tuple
import cursor
import sys
import time
from tqdm import tqdm

# ANSI escape codes for highlighting
HIGHLIGHT_START = '\033[47;30m'
HIGHLIGHT_END = '\033[0m'

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
                        tqdm.write(f"Fetching: {full_path}")
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

def load_repos(repo_db_file: str) -> List[str]:
    if os.path.exists(repo_db_file):
        with open(repo_db_file, 'r', encoding='utf-8') as f:
            try:
                repos = json.load(f)
                if isinstance(repos, list):
                    return repos
            except Exception:
                pass
    return []

def save_repos(repos: List[str], repo_db_file: str):
    with open(repo_db_file, 'w', encoding='utf-8') as f:
        json.dump(repos, f, ensure_ascii=False, indent=4)

def get_repo_choice(repos: List[str]) -> str | None:
    """Displays a list of repositories and lets the user choose one, including an exit option."""

    options = repos + ["Enter new repository", "Exit"]
    current_selection = 0
    repo_url = None

    with cursor.HiddenCursor():
        while True:
            print("\033[?25l")  # Hide cursor
            print("\033[H\033[J")  # Clear screen
            print("Saved GitHub repository URLs:")

            for idx, option in enumerate(options):
                if idx == current_selection:
                    print(f"{HIGHLIGHT_START}{idx + 1}. {option}{HIGHLIGHT_END}")
                else:
                    print(f"{idx + 1}. {option}")


            key = getch()

            if key == '\x1b[A' or key == 'k':  # Up arrow or 'k'
                current_selection = max(0, current_selection - 1)
            elif key == '\x1b[B' or key == 'j':  # Down arrow or 'j'
                current_selection = min(len(options) - 1, current_selection + 1)
            elif key == '\r':  # Enter key
                selected_option = options[current_selection]
                if selected_option == "Exit":
                    return None
                elif selected_option == "Enter new repository":
                    repo_url = input("Enter a new GitHub repository URL: ").strip()
                else:
                    repo_url = selected_option
                break
            elif key == '\x1b': # ESC  (Optional:  Another way to exit)
                return None
    return repo_url

def getch():
    """Gets a single character from standard input."""
    if os.name == 'nt':  # Windows
        import msvcrt
        return msvcrt.getch().decode('utf-8', 'ignore')
    else:  # Linux/macOS
        import termios, tty
        fd = sys.stdin.fileno()
        old_settings = termios.tcgetattr(fd)
        try:
            tty.setraw(sys.stdin.fileno())
            ch = sys.stdin.read(1)

            # Handle arrow keys
            if ch == '\x1b':
                ch += sys.stdin.read(2)
        finally:
            termios.tcsetattr(fd, termios.TCSADRAIN, old_settings)
        return ch

def main():
    token = os.getenv('GITHUB_TOKEN')
    if not token:
        print("Error: GITHUB_TOKEN environment variable is not set")
        return

    script_dir = os.path.dirname(os.path.abspath(__file__))
    output_dir = os.path.join(script_dir, "output")
    output_md_dir = os.path.join(output_dir, "md")
    output_json_dir = os.path.join(output_dir, "json")
    os.makedirs(output_md_dir, exist_ok=True)
    os.makedirs(output_json_dir, exist_ok=True)

    repos_file = os.path.join(output_json_dir, "repos.json")
    repos = load_repos(repos_file)

    repo_url = get_repo_choice(repos)

    if not repo_url:
        print("Operation cancelled.")
        return

    if repo_url not in repos and repo_url is not None :  #added repo_url is not None
        repos.append(repo_url)
        save_repos(repos, repos_file)


    analyzer = GitHubRepoAnalyzer(token, repo_url)
    output_file = os.path.join(output_md_dir, f"{analyzer.repo}.md")

    try:
        with tqdm(desc="Analyzing repository", unit="file") as pbar:
            structure, contents = analyzer.analyze_repo()
            pbar.total = len(contents)
            pbar.update(pbar.total)

        save_analysis(structure, contents, output_file)
        full_output_path = os.path.abspath(output_file)
        print(f"\nAnalysis completed successfully. Results saved to:\n{full_output_path}")

        try:
            import tiktoken
            encoding = tiktoken.encoding_for_model("gpt-3.5-turbo")
            with open(output_file, "r", encoding="utf-8") as f:
                output_text = f.read()
            token_count = len(encoding.encode(output_text))
            print(f"Token count: {token_count} tokens")
        except ImportError:
            print("tiktoken is not installed. Please install it via 'pip install tiktoken' to compute token count.")

    except Exception as e:
        print(f"Error: {str(e)}")


if __name__ == '__main__':
    main()