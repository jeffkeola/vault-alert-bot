namespace Core.Services
{
    using System;
    using System.Text;
    using System.Text.Json;

    using Core.Models;

    using Microsoft.Extensions.DependencyInjection;

    public interface IHyperliquidService
    {
        Task<HyperliquidSnapshot> GetLatestSnapshotAsync(HyperliquidUser user);
        Task<List<string>> RefreshAsync(HyperliquidUser user);
        Task<HyperliquidApiSnapshot> GetApiSnapshotAsync(HyperliquidUser user);
        Task<List<string>> GetLastChangeAsync(HyperliquidUser user);

        // Task CreateHyperliquidResponseAsync(HyperliquidInfoResponse response, HyperliquidUser user);
        ServiceLifetime Lifetime { get; }
    }

    public class HyperliquidUserRequest
    {
        public string Type { get; set; }
        public string User { get; set; }
    }

    public class HyperliquidService : IHyperliquidService
    {
        public const string BaseUrl = "https://api.hyperliquid.xyz";
        public static string UserInfoUrl = $"{BaseUrl}/info";

        protected readonly IHttpClientFactory HttpClientFactory;
        protected readonly JsonSerializerOptions JsonOptions;
        protected readonly IHyperliquidDatabaseClient HyperliquidDatabaseClient;

        public HyperliquidService(IHttpClientFactory clientFactory, IHyperliquidDatabaseClient hyperliquidDatabaseClient)
        {
            this.HttpClientFactory = clientFactory;
            this.JsonOptions = new JsonSerializerOptions { PropertyNamingPolicy = JsonNamingPolicy.CamelCase, WriteIndented = true };
            this.HyperliquidDatabaseClient = hyperliquidDatabaseClient;
        }

        public ServiceLifetime Lifetime => ServiceLifetime.Singleton;


        public async Task<List<string>> GetLastChangeAsync(HyperliquidUser user)
        {
            var (current, previous) = await this.HyperliquidDatabaseClient.GetCurrentAndPreviousSnasphotsAsync(user);
            if (current == null && previous == null)
            {
                return null;
            }
            if (previous == null)
            {
                return new List<string>();
            }

            return ExtensionMethods.GetChangedPositions(user, previous, current);
        }
        public async Task<HyperliquidSnapshot> GetLatestSnapshotAsync(HyperliquidUser user)
        {
            return await this.HyperliquidDatabaseClient.GetCurrentSnasphotAsync(user);
        }

        public async Task<List<string>> RefreshAsync(HyperliquidUser user)
        {
            var previousSnapshot = await this.GetLatestSnapshotAsync(user);
            var apiResponse = await this.GetApiSnapshotAsync(user);

            if (previousSnapshot == null)
            {
                await this.HyperliquidDatabaseClient.CreateSnapshotAsync(apiResponse, user);
                return new List<string>
                {
                    $"Subcription Created for {user.Name}"
                };
            }

            var changes = ExtensionMethods.GetChangedPositions(user, previousSnapshot.Positions, apiResponse.AssetPositions.Select(p => p.Position).ToList());

            if (changes.Count == 0)
            {
                // don't save
                return new List<string>();
            }

            var newSnapshot = await this.HyperliquidDatabaseClient.CreateSnapshotAsync(apiResponse, user);
            return ExtensionMethods.GetChangedPositions(user, previousSnapshot, newSnapshot);
        }

        public async Task<HyperliquidApiSnapshot> GetApiSnapshotAsync(HyperliquidUser user)
        {
            using (HttpClient client = HttpClientFactory.CreateClient("hyperliquid"))
            {
                var request = new HyperliquidUserRequest()
                {
                    User = user.Id,
                    Type = "clearinghouseState"
                };

                var requestBody = JsonSerializer.Serialize(request, this.JsonOptions);
                var content = new StringContent(requestBody, Encoding.UTF8, "application/json");
                HttpResponseMessage httpResponse = await client.PostAsync(UserInfoUrl, content);

                if (httpResponse.IsSuccessStatusCode)
                {
                    string jsonResponse = await httpResponse.Content.ReadAsStringAsync();
                    Console.WriteLine("API Response: " + jsonResponse);

                    return JsonSerializer.Deserialize<HyperliquidApiSnapshot>(jsonResponse, this.JsonOptions);
                }

                throw new Exception($"API Error: {httpResponse.StatusCode}");
            }
        }
    }
}