@description('Name of the App Service Plan')
param name string

@description('Azure region for the App Service Plan')
param location string

@description('SKU for the App Service Plan (e.g. B1, B2, S1, P1v3)')
param sku string = 'B1'

@description('Tags applied to the resource')
param tags object = {}

resource appServicePlan 'Microsoft.Web/serverfarms@2024-04-01' = {
  name: name
  location: location
  tags: tags
  kind: 'linux'
  properties: {
    reserved: true // required for Linux
  }
  sku: {
    name: sku
  }
}

@description('Resource ID of the App Service Plan')
output id string = appServicePlan.id

@description('Name of the App Service Plan')
output name string = appServicePlan.name
