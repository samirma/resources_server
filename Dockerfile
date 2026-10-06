FROM python:3.11-slim AS base

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY main.py openapi.py ./
COPY templates/ templates/

# Runs the unit tests with the 100% line and branch coverage gate (.coveragerc).
# The runtime stage copies its marker, so a failing suite fails the build.
FROM base AS test

COPY requirements-dev.txt pytest.ini .coveragerc init.sh ./
COPY high_level_spec.md agent_skill.md SKILL.md ./
COPY tests/ tests/
RUN pip install --no-cache-dir -r requirements-dev.txt \
    && python -m pytest -q -p no:cacheprovider \
    && touch /tmp/tests-passed

FROM base

COPY --from=test /tmp/tests-passed /tmp/tests-passed

RUN useradd --system --no-create-home appuser
USER appuser

EXPOSE 3100

CMD ["python", "main.py"]
