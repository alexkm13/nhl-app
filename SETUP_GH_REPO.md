# GitHub Repository Setup Instructions

This guide will help you create a private GitHub repository and push your code.

## Option 1: Using GitHub CLI (Recommended)

1. **Authenticate with GitHub CLI:**
   ```bash
   gh auth login
   ```
   Follow the prompts to authenticate via browser or SSH.

2. **Create the private repository and push:**
   ```bash
   cd /Users/alex/nhl-app
   gh repo create nhl-app --private --source=. --remote=origin --push
   ```

## Option 2: Manual Setup via GitHub Website

1. **Create the repository on GitHub:**
   - Go to https://github.com/new
   - Repository name: `nhl-app`
   - Set to **Private**
   - Do NOT initialize with README, .gitignore, or license
   - Click "Create repository"

2. **Push your code:**
   ```bash
   cd /Users/alex/nhl-app
   git remote add origin git@github.com:alexkm13/nhl-app.git
   git push -u origin main
   ```

## Verify Setup

After pushing, verify with:
```bash
git remote -v
git log --oneline
```
