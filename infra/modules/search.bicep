@description('Name of the Azure AI Search service')
param name string

@description('Azure region')
param location string

@description('SKU tier (free, basic, standard, standard2, standard3, storage_optimized_l1, storage_optimized_l2)')
param sku string = 'basic'

@description('Number of replicas (increase for higher availability/throughput)')
param replicaCount int = 1

@description('Number of partitions (increase for more index storage)')
param partitionCount int = 1

resource searchService 'Microsoft.Search/searchServices@2024-06-01-preview' = {
  name: name
  location: location
  sku: {
    name: sku
  }
  properties: {
    replicaCount: replicaCount
    partitionCount: partitionCount
    hostingMode: 'default'
    publicNetworkAccess: 'enabled'
    semanticSearch: 'standard'
  }
}

@description('Resource ID of the Azure AI Search service')
output id string = searchService.id

@description('Name of the Azure AI Search service')
output name string = searchService.name

@description('Endpoint URL of the Azure AI Search service')
output endpoint string = 'https://${name}.search.windows.net'
