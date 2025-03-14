import os
import re
import json
import base64
import asyncio
import aiohttp
import time
import aiofiles
from typing import Dict, List, Tuple
import cursor
import sys
from tqdm import tqdm
import tiktoken

# Cache expiration (1 hour)
CACHE_EXPIRY_SECONDS = 3600

# Directory for file cache
FILE_CACHE_DIR_NAME = "file_cache"

# ANSI codes for highlighting
HIGHLIGHT_START = '\033[47;30m'

HIGHLIGHT_END = '\033[0m'

# Comment patterns for various languages
COMMENT_PATTERNS = {
    'Python': r'#.*',
    'JavaScript': r'//.*|/\*[\s\S]*?\*/',
    'Java': r'//.*|/\*[\s\S]*?\*/',
    'C++': r'//.*|/\*[\s\S]*?\*/',
    'HTML': r'<!--[\s\S]*?-->',
    'CSS': r'/\*[\s\S]*?\*/',
    'C': r'//.*|/\*[\s\S]*?\*/',
    'C#': r'//.*|/\*[\s\S]*?\*/',
    'TypeScript': r'//.*|/\*[\s\S]*?\*/',
    'Kotlin': r'//.*|/\*[\s\S]*?\*/',
    'Swift': r'//.*|/\*[\s\S]*?\*/',
    'Dart': r'//.*|/\*[\s\S]*?\*/',
}

def get_language_from_extension(path: str) -> str:
    """Detect programming language from file extension."""
    extension = os.path.splitext(path)[1].lower()
    return {
        '.py': 'Python',
        '.js': 'JavaScript',
        '.java': 'Java',
        '.cpp': 'C++', '.cc': 'C++', '.cxx': 'C++',
        '.html': 'HTML',
        '.css': 'CSS',
        '.c': 'C',
        '.cs': 'C#',
        '.ts': 'TypeScript',
        '.kt': 'Kotlin',
        '.swift': 'Swift',
        '.dart': 'Dart'
    }.get(extension)

def extract_comments(content: str, language: str) -> str:
    """Extract comments from content based on language."""
    if language not in COMMENT_PATTERNS:
        return ""
    pattern = COMMENT_PATTERNS[language]
    comments = re.findall(pattern, content, re.MULTILINE)
    return "\n".join(comments)

class GitHubRepoAnalyzer:
    def __init__(self, token: str, repo_url: str, file_cache_dir: str):
        self.token = token
        self.owner, self.repo = self._parse_github_url(repo_url)
        self.base_url = f'https://api.github.com/repos/{self.owner}/{self.repo}'
        self.content_cache: Dict[str, str] = {}
        self.file_cache_dir = file_cache_dir

    def _parse_github_url(self, url: str) -> Tuple[str, str]:
        """Parse GitHub URL to get owner and repo."""
        patterns = [
            r'github\.com[:/]([^/]+)/([^/\.]+)(?:\.git)?$',
            r'github\.com/([^/]+)/([^/]+)/?$'
        ]
        for pattern in patterns:
            match = re.search(pattern, url)
            if match:
                return match.groups()
        raise ValueError("Invalid GitHub URL")

    async def get_contents(self, path: str, session: aiohttp.ClientSession) -> List[Dict]:
        """Fetch directory contents from GitHub API."""
        url = f'{self.base_url}/contents/{path}' if path else f'{self.base_url}/contents'
        async with session.get(url) as response:
            response.raise_for_status()
            return await response.json()

    async def get_file_content(self, file_api_url: str, session: aiohttp.ClientSession, sha: str = None) -> str:
        """Fetch file content, using cache if available."""
        if file_api_url in self.content_cache:
            return self.content_cache[file_api_url]
        if sha:
            cache_path = os.path.join(self.file_cache_dir, f"{sha}.cache")
            if os.path.exists(cache_path):
                try:
                    async with aiofiles.open(cache_path, 'r', encoding='utf-8') as cf:
                        content = await cf.read()
                    self.content_cache[file_api_url] = content
                    return content
                except Exception:
                    pass
        async with session.get(file_api_url) as response:
            response.raise_for_status()
            json_resp = await response.json()
            if 'content' not in json_resp:
                content = "Non-text content or unexpected format."
            else:
                try:
                    content = base64.b64decode(json_resp['content']).decode('utf-8')
                except Exception:
                    content = "Error decoding content (possibly binary)."
            self.content_cache[file_api_url] = content
            if sha:
                try:
                    async with aiofiles.open(cache_path, 'w', encoding='utf-8') as cf:
                        await cf.write(content)
                except Exception:
                    pass
            return content

    async def get_default_branch(self, session: aiohttp.ClientSession) -> str:
        """Get repository's default branch."""
        url = f'https://api.github.com/repos/{self.owner}/{self.repo}'
        async with session.get(url) as response:
            response.raise_for_status()
            data = await response.json()
            return data['default_branch']

    async def get_git_tree(self, session: aiohttp.ClientSession) -> Dict:
        """Fetch recursive git tree for default branch."""
        default_branch = await self.get_default_branch(session)
        tree_url = f'{self.base_url}/git/trees/{default_branch}?recursive=1'
        async with session.get(tree_url) as response:
            response.raise_for_status()
            return await response.json()

    async def analyze_repo(self, session: aiohttp.ClientSession, pbar, tree: List[Dict] = None) -> Tuple[List[str], Dict[str, str], int, List[Tuple[str, int, int]]]:
        """Analyze repository: structure, contents, file count, token counts."""
        if tree is None:
            tree = await self.get_git_tree(session)
            tree = tree.get("tree", [])
        nested = build_nested_dict(tree)
        structure = nested_dict_to_tree_str(nested)
        file_api_data = {
            item['path']: (item['url'], item.get('sha'))
            for item in tree if item.get('type') == 'blob'
        }
        file_count = len(file_api_data)

        async def fetch_with_progress(path: str, url: str, sha: str):
            try:
                content = await self.get_file_content(url, session, sha)
            except Exception as e:
                content = f"Error reading file: {str(e)}"
            pbar.update(1)
            return path, content

        tasks = [fetch_with_progress(path, url, sha) for path, (url, sha) in file_api_data.items()]
        results = await asyncio.gather(*tasks)
        contents = {path: content for path, content in results}

        encoding = tiktoken.encoding_for_model("gpt-3.5-turbo")
        token_counts = []
        for path, content in contents.items():
            try:
                total_tokens = len(encoding.encode(content))
                language = get_language_from_extension(path)
                comment_tokens = 0
                if language:
                    comments = extract_comments(content, language)
                    comment_tokens = len(encoding.encode(comments))
                token_counts.append((path, total_tokens, comment_tokens))
            except Exception as e:
                print(f"Error calculating token count for {path}: {str(e)}")

        return structure, contents, file_count, token_counts

def build_nested_dict(tree: List[Dict]) -> dict:
    """Build nested dictionary from git tree."""
    nested = {}
    for item in tree:
        parts = item['path'].split('/')
        node = nested
        for i, part in enumerate(parts):
            if i == len(parts) - 1:
                if item['type'] == 'tree':
                    node.setdefault(part, {})
                else:
                    node[part] = None
            else:
                node = node.setdefault(part, {})
    return nested

def nested_dict_to_tree_str(nested: dict, prefix="") -> List[str]:
    """Convert nested dict to tree string."""
    lines = []
    keys = sorted(nested.keys(), key=lambda k: (0 if isinstance(nested[k], dict) else 1, k.lower()))
    for i, key in enumerate(keys):
        is_last = i == len(keys) - 1
        connector = "└── " if is_last else "├── "
        lines.append(prefix + connector + key)
        if isinstance(nested[key], dict):
            new_prefix = prefix + ("    " if is_last else "│   ")
            lines.extend(nested_dict_to_tree_str(nested[key], new_prefix))
    return lines

def save_analysis(structure: List[str], contents: Dict[str, str], output_file: str):
    """Save repo structure and contents to markdown."""
    with open(output_file, 'w', encoding='utf-8') as f:
        f.write("# Repository Structure\n\n```\n")
        f.write("\n".join(structure))
        f.write("\n```\n\n# File Contents\n\n")
        for path, content in contents.items():
            f.write(f"## {path}\n\n```\n{content}\n```\n\n")

def load_repos(repo_db_file: str) -> List[str]:
    """Load repo list from JSON file."""
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
    """Save repo list to JSON file."""
    with open(repo_db_file, 'w', encoding='utf-8') as f:
        json.dump(repos, f, ensure_ascii=False, indent=4)

async def load_git_tree_cache(cache_path: str) -> Dict | None:
    """Load cached git tree from JSON."""
    if os.path.exists(cache_path):
        try:
            async with aiofiles.open(cache_path, 'r', encoding='utf-8') as f:
                data = json.loads(await f.read())
            if isinstance(data, dict):
                return data
        except Exception:
            pass
    return None

async def save_git_tree_cache(cache_path: str, cache_data: Dict):
    """Save git tree to JSON cache."""
    async with aiofiles.open(cache_path, 'w', encoding='utf-8') as f:
        await f.write(json.dumps(cache_data, ensure_ascii=False, indent=4))

def get_repo_choice(repos: List[str]) -> str | None:
    """Interactive menu to select repo."""
    options = repos + ["Enter new repository", "Exit"]
    current_selection = 0
    with cursor.HiddenCursor():
        while True:
            print("\033[?25l\033[H\033[J")
            print("Saved GitHub repository URLs:")
            for idx, option in enumerate(options):
                print(f"{HIGHLIGHT_START if idx == current_selection else ''}{idx + 1}. {option}{HIGHLIGHT_END if idx == current_selection else ''}")
            key = getch()
            if key in ('\x1b[A', 'k'):
                current_selection = max(0, current_selection - 1)
            elif key in ('\x1b[B', 'j'):
                current_selection = min(len(options) - 1, current_selection + 1)
            elif key == '\r':
                selected = options[current_selection]
                if selected == "Exit":
                    return None
                elif selected == "Enter new repository":
                    return input("Enter a new GitHub repository URL: ").strip()
                return selected
            elif key == '\x1b':
                return None

def getch():
    """Get single character input."""
    if os.name == 'nt':
        import msvcrt
        return msvcrt.getch().decode('utf-8', 'ignore')
    else:
        import termios, tty
        fd = sys.stdin.fileno()
        old_settings = termios.tcgetattr(fd)
        try:
            tty.setraw(fd)
            ch = sys.stdin.read(1)
            if ch == '\x1b':
                ch += sys.stdin.read(2)
        finally:
            termios.tcsetattr(fd, termios.TCSADRAIN, old_settings)
        return ch

async def main_async():
    """Main function to analyze GitHub repo."""
    token = os.getenv('GITHUB_TOKEN')
    if not token:
        print("Error: GITHUB_TOKEN not set")
        return

    script_dir = os.path.dirname(os.path.abspath(__file__))
    output_dir = os.path.join(script_dir, "output")
    output_md_dir = os.path.join(output_dir, "md")
    output_json_dir = os.path.join(output_dir, "json")
    file_cache_dir = os.path.join(output_json_dir, FILE_CACHE_DIR_NAME)
    os.makedirs(output_md_dir, exist_ok=True)
    os.makedirs(output_json_dir, exist_ok=True)
    os.makedirs(file_cache_dir, exist_ok=True)

    repos_file = os.path.join(output_json_dir, "repos.json")
    repos = load_repos(repos_file)
    repo_url = get_repo_choice(repos)
    if not repo_url:
        print("Operation cancelled.")
        return
    if repo_url not in repos:
        repos.append(repo_url)
        save_repos(repos, repos_file)

    analyzer = GitHubRepoAnalyzer(token, repo_url, file_cache_dir)
    headers = {'Authorization': f'token {token}'}
    async with aiohttp.ClientSession(headers=headers) as session:
        cache_file = os.path.join(output_json_dir, f"{analyzer.owner}_{analyzer.repo}_tree.json")
        cached_data = await load_git_tree_cache(cache_file)

        default_branch = await analyzer.get_default_branch(session)
        branch_url = f'https://api.github.com/repos/{analyzer.owner}/{analyzer.repo}/branches/{default_branch}'
        async with session.get(branch_url) as response:
            response.raise_for_status()
            branch_data = await response.json()
        current_commit_sha = branch_data["commit"]["sha"]

        if cached_data is None or cached_data.get("commit_sha") != current_commit_sha:
            print("Fetching git tree from API...")
            tree_json = await analyzer.get_git_tree(session)
            cache_data = {
                "commit_sha": current_commit_sha,
                "tree": tree_json,
                "cached_at": time.time()
            }
            await save_git_tree_cache(cache_file, cache_data)
        else:
            print("Using cached git tree.")
            cache_data = cached_data

        tree = cache_data["tree"].get("tree", [])
        if not tree:
            print("Warning: Repository tree is empty.")
            return

        total_files = sum(1 for item in tree if item.get('type') == 'blob')
        output_file = os.path.join(output_md_dir, f"{analyzer.repo}.md")
        with tqdm(total=total_files, desc="Analyzing repository", unit="file") as pbar:
            structure, contents, _, token_counts = await analyzer.analyze_repo(session, pbar, tree)
        save_analysis(structure, contents, output_file)
        full_output_path = os.path.abspath(output_file)
        print(f"\nAnalysis completed successfully. Results saved to:\n{full_output_path}")

        token_counts.sort(key=lambda x: x[1])
        print("\nIndividual file token counts (ascending order):")
        for path, total_tokens, comment_tokens in token_counts:
            print(f"{path}: \033[1;33m{total_tokens}\033[0m tokens (comments: \033[1;33m{comment_tokens}\033[0m tokens)")
        total_tokens_sum = sum(total_tokens for _, total_tokens, _ in token_counts)
        total_comment_tokens_sum = sum(comment_tokens for _, _, comment_tokens in token_counts)
        print(f"\nTotal token count: \033[1;33m{total_tokens_sum}\033[0m tokens (comments: \033[1;33m{total_comment_tokens_sum}\033[0m tokens)")

def main():
    """Run the async main function."""
    asyncio.run(main_async())

if __name__ == '__main__':
    main()