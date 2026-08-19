# Contributing to PipelineGuard

Thank you for your interest in contributing to PipelineGuard!

## Setup Instructions

1. Clone the repository:
   ```bash
   git clone https://github.com/Tejeshyewale/pipelineguard.git
   cd pipelineguard
   ```

2. Create a virtual environment (optional but recommended):
   ```bash
   python -m venv venv
   source venv/bin/activate  # On Windows: venv\Scripts\activate
   ```

3. Install development dependencies:
   ```bash
   pip install -r requirements-dev.txt
   ```

## Running Tests

PipelineGuard uses `pytest` for testing. You can run the test suite with:

```bash
pytest tests/ -v
```

All tests are designed to run without any external dependencies or network calls, using a fake client for reliability logic verification.

## Submitting a Pull Request

1. Fork the repository and create your feature branch (`git checkout -b my-new-feature`).
2. Make sure all tests pass by running `pytest tests/ -v`.
3. Keep your code style consistent with the rest of the project.
4. Commit your changes (`git commit -am 'Add some feature'`).
5. Push to the branch (`git push origin my-new-feature`).
6. Create a new Pull Request.

Please ensure any new features include appropriate tests.
