@description('Name of the storage account (3-24 chars, lowercase alphanumeric only)')
param name string

@description('Azure region')
param location string

@description('Storage account SKU')
param sku string = 'Standard_LRS'

@description('Name of the table used for user study logging')
param tableName string = 'userstudylogs'

@description('Tags applied to the resource')
param tags object = {}

resource storageAccount 'Microsoft.Storage/storageAccounts@2023-05-01' = {
  name: name
  location: location
  tags: tags
  sku: {
    name: sku
  }
  kind: 'StorageV2'
  properties: {
    minimumTlsVersion: 'TLS1_2'
    allowBlobPublicAccess: false
    supportsHttpsTrafficOnly: true
  }
}

resource tableService 'Microsoft.Storage/storageAccounts/tableServices@2023-05-01' = {
  parent: storageAccount
  name: 'default'
}

resource studyLogTable 'Microsoft.Storage/storageAccounts/tableServices/tables@2023-05-01' = {
  parent: tableService
  name: tableName
}

@description('Resource ID of the storage account')
output id string = storageAccount.id

@description('Name of the storage account')
output name string = storageAccount.name

@description('Connection string for the storage account')
#disable-next-line outputs-should-not-contain-secrets
output connectionString string = 'DefaultEndpointsProtocol=https;AccountName=${storageAccount.name};AccountKey=${storageAccount.listKeys().keys[0].value};EndpointSuffix=${environment().suffixes.storage}'
