@description('Name of the backend App Service')
param name string

@description('Azure region')
param location string

@description('Resource ID of the App Service Plan')
param appServicePlanId string

@description('Linux runtime stack')
param linuxFxVersion string = 'PYTHON|3.12'

// --- App settings (wired to Python Pydantic config) ---

@description('Azure OpenAI endpoint URL')
param azureOpenaiEndpoint string

@secure()
@description('Azure OpenAI API key')
param azureOpenaiApiKey string

@description('Azure OpenAI API version')
param azureOpenaiApiVersion string = '2024-12-01-preview'

@description('Primary model deployment name')
param azureOpenaiDeployment string = 'gpt-5.4'

@description('Mini/utility model deployment name')
param azureOpenaiMiniDeployment string = 'gpt-5.4-nano'

@description('Embedding model deployment name')
param azureOpenaiEmbeddingDeployment string = 'text-embedding-3-small'

@description('Comma-separated list of available deployment names (optional)')
param azureOpenaiAvailableDeployments string = ''

@description('Azure AI Search endpoint URL')
param azureSearchEndpoint string

@secure()
@description('Azure AI Search admin key')
param azureSearchKey string

@description('Azure AI Search regulation index name')
param azureSearchIndexName string = 'campuslmu-regulations-v2'

@description('Azure AI Search web index name')
param azureSearchWebIndexName string = 'campuslmu-web-v1'

@secure()
@description('Redis connection string (rediss://...)')
param redisConnectionString string = ''

@description('Allowed CORS origins (comma-separated)')
param allowedOrigins string = 'http://localhost:3000'

@description('Directory for feedback storage (persistent on App Service)')
param feedbackDir string = '/home/feedback'

resource backendApp 'Microsoft.Web/sites@2024-04-01' = {
  name: name
  location: location
  kind: 'app,linux'
  properties: {
    serverFarmId: appServicePlanId
    httpsOnly: true
    siteConfig: {
      linuxFxVersion: linuxFxVersion
      alwaysOn: true
      appCommandLine: 'gunicorn -w 4 -k uvicorn.workers.UvicornWorker --bind 0.0.0.0:8000 app.main:app'
      ftpsState: 'Disabled'
      minTlsVersion: '1.2'
      appSettings: [
        { name: 'AZURE_OPENAI_ENDPOINT', value: azureOpenaiEndpoint }
        { name: 'AZURE_OPENAI_API_KEY', value: azureOpenaiApiKey }
        { name: 'AZURE_OPENAI_API_VERSION', value: azureOpenaiApiVersion }
        { name: 'AZURE_OPENAI_DEPLOYMENT', value: azureOpenaiDeployment }
        { name: 'AZURE_OPENAI_MINI_DEPLOYMENT', value: azureOpenaiMiniDeployment }
        { name: 'AZURE_OPENAI_EMBEDDING_DEPLOYMENT', value: azureOpenaiEmbeddingDeployment }
        { name: 'AZURE_OPENAI_AVAILABLE_DEPLOYMENTS', value: azureOpenaiAvailableDeployments }
        { name: 'AZURE_SEARCH_ENDPOINT', value: azureSearchEndpoint }
        { name: 'AZURE_SEARCH_KEY', value: azureSearchKey }
        { name: 'AZURE_SEARCH_INDEX_NAME', value: azureSearchIndexName }
        { name: 'AZURE_SEARCH_WEB_INDEX_NAME', value: azureSearchWebIndexName }
        { name: 'REDIS_URL', value: redisConnectionString }
        { name: 'ALLOWED_ORIGINS', value: allowedOrigins }
        { name: 'FEEDBACK_DIR', value: feedbackDir }
        { name: 'SCM_DO_BUILD_DURING_DEPLOYMENT', value: 'true' }
      ]
    }
  }
}

@description('Resource ID of the backend App Service')
output id string = backendApp.id

@description('Name of the backend App Service')
output name string = backendApp.name

@description('Default hostname of the backend App Service')
output defaultHostName string = backendApp.properties.defaultHostName
