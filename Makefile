# gcloud on this machine dies on system Python 3.13 (pyOpenSSL mismatch). See DECISIONS D-002d.
export CLOUDSDK_PYTHON := /Library/Frameworks/Python.framework/Versions/3.14/bin/python3

.PHONY: dev test seed schemas check-schema types record rehearse verify image deploy probe-geap clean

dev:        ## run api + web against emulators
	docker compose up --build

test:       ## full suite, replay mode, no cloud credentials
	DEMO_MODE=replay PLATFORM_BACKEND=local ./.venv/bin/python -m pytest backend/tests -q

seed:
	python3 -m backend.app.seed.generate

schemas:    ## regenerate schemas/ from the Pydantic models (commit the result)
	cd backend && ../.venv/bin/python -m app.models.export_schema ../schemas

check-schema: ## fail if schemas/ has drifted from the models
	./.venv/bin/python -m pytest backend/tests/test_schema_contract.py -q

types:      ## regenerate web/src/lib/types.ts from the schema bundle
	cd backend && ../.venv/bin/python -m app.models.export_schema ../schemas
	npx --yes json-schema-to-typescript schemas/interdict.bundle.schema.json \
	  -o web/src/lib/generated-types.ts --no-additionalProperties
	@echo "Generated web/src/lib/generated-types.ts — reconcile with lib/types.ts by hand."

record:     ## populate the replay cache from live models. COSTS ~$0.06. See CACHE.md
	@grep -q '^DEMO_MODE=record' .env || (echo "set DEMO_MODE=record in .env first"; exit 1)
	@echo "Recording all five scenarios against $$(grep ^LLM_PROVIDER .env)"
	@curl -s -X POST localhost:8077/api/demo/reset -m 60 -o /dev/null
	@for s in S1 S2 S3 S4 S5; do \
	  printf "  %s " $$s; \
	  curl -s -X POST localhost:8077/api/demo/inject_scenario/$$s -m 300 \
	    | ./.venv/bin/python -c "import sys,json;d=json.load(sys.stdin);print(d.get('outcome') or d.get('state') or d.get('detail','?'))"; \
	done
	@printf "  cross-tenant "
	@curl -s -X POST localhost:8077/api/demo/inject_cross_tenant -m 300 \
	  | ./.venv/bin/python -c "import sys,json;d=json.load(sys.stdin);print(d.get('outcome') or d.get('detail','?'))"
	@printf "  clock wake   "
	@curl -s -X POST localhost:8077/api/demo/advance_clock -H 'content-type: application/json' \
	  -d '{"days":4}' -m 300 \
	  | ./.venv/bin/python -c "import sys,json;d=json.load(sys.stdin);print([w.get('outcome') for w in d.get('woken',[])])"

rehearse:   ## run every demo beat and assert per-beat wall-clock
	python3 -m backend.tests.rehearse

probe-geap: ## re-verify GEAP surfaces and locations (see DECISIONS D-002)
	@P=$$(gcloud config get-value project 2>/dev/null); T=$$(gcloud auth print-access-token); \
	printf "runtime  us-central1  "; curl -s -o /dev/null -w "HTTP %{http_code}\n" -H "Authorization: Bearer $$T" \
	  "https://us-central1-aiplatform.googleapis.com/v1beta1/projects/$$P/locations/us-central1/reasoningEngines"; \
	printf "registry global       "; curl -s -o /dev/null -w "HTTP %{http_code}\n" -H "Authorization: Bearer $$T" \
	  "https://aiplatform.googleapis.com/v1beta1/projects/$$P/locations/global/agents"

verify:     ## prove the whole runbook replays offline with no credentials
	@DEMO_MODE=replay PLATFORM_BACKEND=local ./.venv/bin/python -m pytest backend/tests -q
	@cd web && npx tsc --noEmit && npx vite build >/dev/null && echo "web: tsc + build clean"

# --- deployment ------------------------------------------------------------------------------
# ONE INTERACTIVE STEP FIRST, and it is not one this repo can do for you:
#
#   gcloud auth login            # as the account that OWNS the project
#   gcloud config set project $(GCP_PROJECT)
#
# The other gcloud accounts on this machine cannot see the project (ADC can, but `gcloud run
# deploy` uses gcloud's own credentials, not ADC). `make deploy` fails fast if that is not done.
GCP_PROJECT ?= interdict-demo-57216
REGION      ?= us-central1
SERVICE     ?= interdict

image:      ## build the container locally and prove it serves the demo
	docker build -t $(SERVICE):local .
	@echo "run it:  docker run --rm -p 8099:8080 -e DEMO_MODE=replay $(SERVICE):local"

deploy:     ## build and deploy to Cloud Run. Requires `gcloud auth login` as the project owner.
	@gcloud projects describe $(GCP_PROJECT) >/dev/null 2>&1 || ( \
	  echo "gcloud cannot see $(GCP_PROJECT)."; \
	  echo "Run: gcloud auth login   (as the account that owns the project)"; \
	  echo "then: gcloud config set project $(GCP_PROJECT)"; exit 1 )
	gcloud run deploy $(SERVICE) \
	  --source . \
	  --project $(GCP_PROJECT) \
	  --region $(REGION) \
	  --allow-unauthenticated \
	  --memory 2Gi \
	  --cpu 2 \
	  --timeout 300 \
	  --max-instances 1 \
	  --set-env-vars "DEMO_MODE=$(DEMO_MODE),PLATFORM_BACKEND=local,LLM_PROVIDER=vertex,GCP_PROJECT_ID=$(GCP_PROJECT),VERTEX_LOCATION=global"
	@echo
	@echo "The service account needs Vertex AI access for DEMO_MODE=live:"
	@echo "  gcloud projects add-iam-policy-binding $(GCP_PROJECT) \\"
	@echo "    --member=serviceAccount:$$(gcloud projects describe $(GCP_PROJECT) --format='value(projectNumber)')-compute@developer.gserviceaccount.com \\"
	@echo "    --role=roles/aiplatform.user"

# `replay` by default: a hosted URL a judge can click should not spend model quota or depend on
# one project's rate limits to answer. Deploy live for the recording with `make deploy DEMO_MODE=live`.
DEMO_MODE ?= replay

clean:
	rm -rf dist node_modules .pytest_cache
	find . -name __pycache__ -type d -prune -exec rm -rf {} +
