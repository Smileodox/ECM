@description('Name of the Azure OpenAI account')
param name string

@description('Azure region')
param location string

@description('SKU for the Cognitive Services account')
param sku string = 'S0'

@description('Model deployments — array of {name, model, version, skuName, capacity}')
param deployments array = [
  { name: 'gpt-5.4',       model: 'gpt-5.4',              version: '2026-03-05', skuName: 'GlobalStandard', capacity: 10 }
  { name: 'gpt-5.4-nano',  model: 'gpt-5.4-nano',         version: '2026-03-17', skuName: 'GlobalStandard', capacity: 10 }
  { name: 'gpt-5.1',       model: 'gpt-5.1',              version: '2025-11-13', skuName: 'GlobalStandard', capacity: 10 }
  { name: 'gpt-5-mini',    model: 'gpt-5-mini',           version: '2025-08-07', skuName: 'GlobalStandard', capacity: 10 }
  { name: 'gpt-5-nano',    model: 'gpt-5-nano',           version: '2025-08-07', skuName: 'GlobalStandard', capacity: 10 }
  { name: 'gpt-4.1',       model: 'gpt-4.1',              version: '2025-04-14', skuName: 'GlobalStandard', capacity: 10 }
  { name: 'gpt-4.1-mini',  model: 'gpt-4.1-mini',         version: '2025-04-14', skuName: 'GlobalStandard', capacity: 10 }
  { name: 'text-embedding-3-small', model: 'text-embedding-3-small', version: '1', skuName: 'Standard', capacity: 30 }
]

resource openaiAccount 'Microsoft.CognitiveServices/accounts@2024-10-01' = {
  name: name
  location: location
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
