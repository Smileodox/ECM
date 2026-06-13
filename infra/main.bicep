targetScope = 'resourceGroup'

// ─── Core parameters ────────────────────────────────────────────────────────

@description('Project name used to derive all resource names')
param projectName string

@description('Azure region for all resources')
param location string = 'westeurope'

@description('Environment identifier (poc, staging, prod)')
param environment string = 'poc'

// ─── Secure parameters (passed at deploy time) ─────────────────────────────

@secure()
@description('Azure OpenAI API key — retrieve via `az cognitiveservices account keys list`')
param azureOpenaiApiKey string

@secure()
@description('Azure AI Search admin key — retrieve via `az search admin-key show`')
param azureSearchKey string

@secure()
@description('Redis primary key — retrieve via `az redis list-keys`')
param redisPassword string

// ─── Derived resource names ─────────────────────────────────────────────────

var aspName = 'asp-${projectName}-${environment}'
var backendAppName = 'app-${projectName}-backend-${environment}'
var frontendAppName = 'app-${projectName}-frontend-${environment}'
var openaiName = 'oai-${projectName}-${environment}'
var searchName = 'search-${projectName}-${environment}'
var redisName = 'redis-${projectName}-${environment}'

// ─── App Service Plan ───────────────────────────────────────────────────────

module appServicePlan 'modules/appServicePlan.bicep' = {
  name: 'deploy-asp'
  params: {
    name: aspName
    location: location
  }
}

// ─── Azure OpenAI ───────────────────────────────────────────────────────────

module openai 'modules/openai.bicep' = {
  name: 'deploy-openai'
  params: {
    name: openaiName
    location: location
  }
}

// ─── Azure AI Search ────────────────────────────────────────────────────────

module search 'modules/search.bicep' = {
  name: 'deploy-search'
  params: {
    name: searchName
    location: location
  }
}

// ─── Azure Cache for Redis ──────────────────────────────────────────────────

module redis 'modules/redis.bicep' = {
  name: 'deploy-redis'
  params: {
    name: redisName
    location: location
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
    azureOpenaiApiKey: azureOpenaiApiKey
    azureSearchEndpoint: search.outputs.endpoint
    azureSearchKey: azureSearchKey
    redisConnectionString: 'rediss://:${redisPassword}@${redis.outputs.hostName}:${redis.outputs.sslPort}/0'
    allowedOrigins: 'https://${frontendAppName}.azurewebsites.net'
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
