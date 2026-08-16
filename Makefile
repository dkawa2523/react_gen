.PHONY: quality-fast quality-pr quality-nightly quality-baseline

quality-fast:
	python -m nox -s quality-fast

quality-pr:
	python -m nox -s quality-pr

quality-nightly:
	python -m nox -s quality-nightly

quality-baseline:
	python -m nox -s quality-baseline
