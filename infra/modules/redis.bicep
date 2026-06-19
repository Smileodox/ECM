@description('Name of the Azure Cache for Redis instance')
param name string

@description('Azure region')
param location string

@description('SKU name (Basic, Standard, Premium)')
param sku string = 'Basic'

@description('Cache capacity (0-6 for Basic/Standard, 1-5 for Premium)')
param capacity int = 0

@description('SKU family (C = Basic/Standard, P = Premium)')
param family string = 'C'

@description('Tags applied to the resource')
param tags object = {}

resource redisCache 'Microsoft.Cache/redis@2024-03-01' = {
  name: name
  location: location
  tags: tags
  properties: {
    sku: {
      name: sku
      family: family
      capacity: capacity
    }
    enableNonSslPort: false
    minimumTlsVersion: '1.2'
    redisConfiguration: {
      'maxmemory-policy': 'allkeys-lru'
    }
  }
}

@description('Resource ID of the Redis cache')
output id string = redisCache.id

@description('Name of the Redis cache')
output name string = redisCache.name

@description('Hostname of the Redis cache')
output hostName string = redisCache.properties.hostName

@description('SSL port of the Redis cache')
output sslPort int = redisCache.properties.sslPort

@description('Primary access key of the Redis cache')
#disable-next-line outputs-should-not-contain-secrets
output key string = redisCache.listKeys().primaryKey

@description('Full Redis connection string (rediss://...)')
#disable-next-line outputs-should-not-contain-secrets
output connectionString string = 'rediss://:${redisCache.listKeys().primaryKey}@${redisCache.properties.hostName}:${redisCache.properties.sslPort}/0'
