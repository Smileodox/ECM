targetScope = 'resourceGroup'

// ─── Core parameters ────────────────────────────────────────────────────────

@description('Project name used to derive all resource names')
param projectName string

@description('Azure region for all resources')
param location string = 'westeurope'

@description('Environment identifier (poc, staging, prod)')
param environment string = 'poc'

@description('App Service Plan SKU (B1, B2, B3, S1, P1v3, …)')
param appServicePlanSku string = 'B1'

@description('Azure OpenAI model deployments — overridable per environment (model availability & SKU quota differ per subscription/region)')
param openaiDeployments array = [
  { name: 'gpt-5.4',       model: 'gpt-5.4',              version: '2026-03-05', skuName: 'GlobalStandard', capacity: 10 }
  { name: 'gpt-5.4-nano',  model: 'gpt-5.4-nano',         version: '2026-03-17', skuName: 'GlobalStandard', capacity: 10 }
  { name: 'gpt-5.1',       model: 'gpt-5.1',              version: '2025-11-13', skuName: 'GlobalStandard', capacity: 10 }
  { name: 'gpt-5-mini',    model: 'gpt-5-mini',           version: '2025-08-07', skuName: 'GlobalStandard', capacity: 10 }
  { name: 'gpt-5-nano',    model: 'gpt-5-nano',           version: '2025-08-07', skuName: 'GlobalStandard', capacity: 10 }
  { name: 'gpt-4.1',       model: 'gpt-4.1',              version: '2025-04-14', skuName: 'GlobalStandard', capacity: 10 }
  { name: 'gpt-4.1-mini',  model: 'gpt-4.1-mini',         version: '2025-04-14', skuName: 'GlobalStandard', capacity: 10 }
  { name: 'text-embedding-3-small', model: 'text-embedding-3-small', version: '1', skuName: 'Standard', capacity: 30 }
]

@description('Mandatory SKF governance tags applied to every resource')
param tags object = {
  apmid: 'apm0006827'
  billingidentifier: 'cl_op_azure'
  fso: 'paul.keck@skf.com'
  itso: 'paul.keck@skf.com'
}

// ─── Derived resource names ─────────────────────────────────────────────────
// Keys are read from the resources this template creates (listKeys), so no
// secrets need to be supplied at deploy time — the stack is self-contained.

var aspName = 'asp-${projectName}-${environment}'
var backendAppName = 'app-${projectName}-backend-${environment}'
var frontendAppName = 'app-${projectName}-frontend-${environment}'
var openaiName = 'oai-${projectName}-${environment}'
var searchName = 'search-${projectName}-${environment}'
var redisName = 'redis-${projectName}-${environment}'
// Storage account names: lowercase alphanumeric only, max 24 chars
var storageName = take(toLower(replace('st${projectName}${environment}', '-', '')), 24)

// ─── App Service Plan ───────────────────────────────────────────────────────

module appServicePlan 'modules/appServicePlan.bicep' = {
  name: 'deploy-asp'
  params: {
    name: aspName
    location: location
    sku: appServicePlanSku
    tags: tags
  }
}

// ─── Azure OpenAI ───────────────────────────────────────────────────────────

module openai 'modules/openai.bicep' = {
  name: 'deploy-openai'
  params: {
    name: openaiName
    location: location
    deployments: openaiDeployments
    tags: tags
  }
}

// ─── Azure AI Search ────────────────────────────────────────────────────────

module search 'modules/search.bicep' = {
  name: 'deploy-search'
  params: {
    name: searchName
    location: location
    tags: tags
  }
}

// ─── Azure Cache for Redis ──────────────────────────────────────────────────

module redis 'modules/redis.bicep' = {
  name: 'deploy-redis'
  params: {
    name: redisName
    location: location
    tags: tags
  }
}

// ─── Azure Storage (user study logging) ─────────────────────────────────────

module storage 'modules/storage.bicep' = {
  name: 'deploy-storage'
  params: {
    name: storageName
    location: location
    tags: tags
  }
}

// ─── Backend App Service ────────────────────────────────────────────────────

module backend 'modules/appServiceBackend.bicep' = {
  name: 'deploy-backend'
  params: {
    name: backendAppName
    location: location
    appServicePlanId: appServicePlan.outputs.id
    azureOpenaiEndpoint: openai.outputs.endpoint
    azureOpenaiApiKey: openai.outputs.key
    azureSearchEndpoint: search.outputs.endpoint
    azureSearchKey: search.outputs.key
    redisConnectionString: redis.outputs.connectionString
    azureStorageConnectionString: storage.outputs.connectionString
    allowedOrigins: 'https://${frontendAppName}.azurewebsites.net'
    tags: tags
  }
}

// ─── Frontend App Service ───────────────────────────────────────────────────

module frontend 'modules/appServiceFrontend.bicep' = {
  name: 'deploy-frontend'
  params: {
    name: frontendAppName
    location: location
    appServicePlanId: appServicePlan.outputs.id
    apiUrl: 'https://${backend.outputs.defaultHostName}'
    tags: tags
  }
}

// ─── Outputs ────────────────────────────────────────────────────────────────

@description('Backend App Service hostname')
output backendHostName string = backend.outputs.defaultHostName

@description('Frontend App Service hostname')
output frontendHostName string = frontend.outputs.defaultHostName

@description('Backend URL')
output backendUrl string = 'https://${backend.outputs.defaultHostName}'

@description('Frontend URL')
output frontendUrl string = 'https://${frontend.outputs.defaultHostName}'

@description('Azure OpenAI endpoint')
output openaiEndpoint string = openai.outputs.endpoint

@description('Azure AI Search endpoint')
output searchEndpoint string = search.outputs.endpoint

@description('Redis hostname')
output redisHostName string = redis.outputs.hostName
