# Contributing to TravEx 🌟

Thank you for your interest in contributing to TravEx! We're excited to have you join our community of developers working to make travel recommendations more accessible and natural through AI-powered voice interactions.

## 🚀 Getting Started

1. **Fork the Repository**
   - Click the 'Fork' button at the top right of this repository
   - Clone your fork locally:
     ```bash
     git clone https://github.com/your-username/travex.git
     cd travex
     ```

2. **Set Up Development Environment**
   - Create and activate a virtual environment:
     ```bash
     python -m venv venv
     source venv/bin/activate  # On Windows: venv\Scripts\activate
     ```
   - Install dependencies:
     ```bash
     pip install -r requirements.txt
     pip install -r requirements-dev.txt  # Development dependencies
     ```
   - Copy and configure environment variables:
     ```bash
     cp .env.example .env
     # Edit .env with your API keys
     ```

3. **Create a Branch**
   - Create a branch for your feature/fix:
     ```bash
     git checkout -b feature/your-feature-name
     # or
     git checkout -b fix/your-fix-name
     ```

## 💻 Development Workflow

1. **Make Your Changes**
   - Write clean, readable code
   - Follow PEP 8 style guide
   - Add type hints where applicable
   - Include docstrings for new functions/classes
   - Add comments for complex logic

2. **Test Your Changes**
   - Add appropriate test cases
   - Run the test suite:
     ```bash
     pytest
     ```
   - Ensure all tests pass
   - Check code coverage:
     ```bash
     pytest --cov=app tests/
     ```

3. **Commit Your Changes**
   - Follow conventional commits:
     ```
     feat: add new feature
     fix: resolve bug
     docs: update documentation
     style: formatting changes
     refactor: code restructuring
     test: add/update tests
     chore: maintenance tasks
     ```
   - Keep commits focused and atomic
   - Write clear commit messages

4. **Submit a Pull Request**
   - Push your changes to your fork
   - Create a Pull Request to the main repository
   - Fill out the PR template completely
   - Link any related issues

## 📝 Documentation

- Add/update documentation for new features
- Include docstrings in code
- Update README.md if needed
- Add examples for new functionality

## 🧪 Testing Guidelines

- Write unit tests for new features
- Include integration tests where appropriate
- Test edge cases and error conditions
- Aim for >80% test coverage
- Test voice interactions thoroughly

## 🎯 What to Work On

1. **Beginner-Friendly Issues**
   - Look for issues tagged with `good-first-issue`
   - Start with documentation improvements
   - Fix small bugs or add tests

2. **Feature Development**
   - Check the project roadmap
   - Look for issues tagged with `help-wanted`
   - Propose new features through issues

3. **Current Focus Areas**
   - Multi-language support
   - User preference persistence
   - Booking system integration
   - Performance optimization
   - Enhanced error handling

## 🚫 Code of Conduct

- Be respectful and inclusive
- Welcome newcomers
- Provide constructive feedback
- Follow the project's code of conduct

## 🏆 Recognition

- All contributors are recognized in CONTRIBUTORS.md
- Significant contributions may earn maintainer status
- We celebrate all types of contributions

## 📞 Getting Help

- Create an issue for questions
- Join our community discussions
- Read the documentation
- Ask for clarification on issues

## 🔄 Review Process

1. **Initial Review**
   - Code quality check
   - Test coverage verification
   - Documentation review

2. **Feedback**
   - Address review comments
   - Make requested changes
   - Update tests if needed

3. **Merge**
   - Squash and merge after approval
   - Clean commit history
   - Delete branch after merge

Thank you for contributing to TravEx! Together, we're making travel recommendations more accessible and natural through AI-powered voice interactions. 🌟 