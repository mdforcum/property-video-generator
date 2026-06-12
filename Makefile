# Shelby Video — Cloud Run operations
# Usage: make deploy | make logs | make url | make health | make open

PROJECT_ID ?= shelby-video
REGION     ?= us-central1
SERVICE    ?= property-video-generator
IMAGE      := $(REGION)-docker.pkg.dev/$(PROJECT_ID)/shelby-images/$(SERVICE):latest

deploy: ## Rebuild image and redeploy (run after any code change)
	gcloud builds submit apps/backend --tag $(IMAGE) --project $(PROJECT_ID)
	gcloud run deploy $(SERVICE) --image $(IMAGE) --region $(REGION) --project $(PROJECT_ID)

logs: ## Tail recent logs
	gcloud run services logs read $(SERVICE) --region $(REGION) --project $(PROJECT_ID) --limit 50

url: ## Print the service URL
	@gcloud run services describe $(SERVICE) --region $(REGION) --project $(PROJECT_ID) --format='value(status.url)'

health: ## Hit the health endpoint
	curl -s $$(make -s url)/health

open: ## Open the Cloud Run console
	@echo https://console.cloud.google.com/run/detail/$(REGION)/$(SERVICE)?project=$(PROJECT_ID)

costs: ## Open billing report
	@echo https://console.cloud.google.com/billing/reports?project=$(PROJECT_ID)

.PHONY: deploy logs url health open costs
