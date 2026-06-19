@description('Name of the Azure OpenAI account')
param name string

@description('Azure region')
param location string

@description('SKU for the Cognitive Services account')
param sku string = 'S0'

@description('Tags applied to the resource')
param tags object = {}

@description('Model deployments — array of {name, model, version, skuName, capacity}. Supplied by main.bicep (single source of truth, overridable per environment for differing model/SKU quota).')
param deployments array

resource openaiAccount 'Microsoft.CognitiveServices/accounts@2024-10-01' = {
  name: name
  location: location
  tags: tags
  kind: 'OpenAI'
  sku: {
    name: sku
  }
  properties: {
    customSubDomainName: name
    publicNetworkAccess: 'Enabled'
  }
}

@batchSize(1)
resource modelDeployments 'Microsoft.CognitiveServices/accounts/deployments@2024-10-01' = [
  for d in deployments: {
    parent: openaiAccount
    name: d.name
    sku: {
      name: d.skuName
      capacity: d.capacity
    }
    properties: {
      model: {
        format: 'OpenAI'
        name: d.model
        version: d.version
      }
    }
  }
]

@description('Azure OpenAI endpoint URL')
output endpoint string = openaiAccount.properties.endpoint

@description('Resource ID of the Azure OpenAI account')
output id string = openaiAccount.id

@description('Name of the Azure OpenAI account')
output name string = openaiAccount.name

@description('Primary API key of the Azure OpenAI account')
#disable-next-line outputs-should-not-contain-secrets
output key string = openaiAccount.listKeys().key1
