using System.Text;
using System.Text.Json;

using Core.Models;

using Microsoft.Extensions.Configuration;

namespace Core.Services
{
    public interface ITelegramService
    {
        Task SendMessagesAsync(HyperliquidUser user, string chatId, List<string> messages);
    }

    public class TelegramRequest
    {
        public string chat_id { get; set; }
        public string text { get; set; }
        public string parse_mode { get; set; }
    }
    public class TelegramService : ITelegramService
    {
        public const string MainChatId = "-4660176219";
        private readonly string BaseUrl;
        protected readonly IHttpClientFactory HttpClientFactory;
        protected readonly JsonSerializerOptions JsonOptions;
        public TelegramService(IHttpClientFactory clientFactory, IConfiguration configuration)
        {
            this.HttpClientFactory = clientFactory;
            this.BaseUrl = configuration.GetConnectionString("TelegramBot");
            this.JsonOptions = new JsonSerializerOptions();
        }

        public async Task SendMessagesAsync(HyperliquidUser user, string chatId, List<string> messages)
        {
            using (HttpClient client = HttpClientFactory.CreateClient("telegram"))
            {
                var url = $"{this.BaseUrl}/sendMessage";
                foreach (var message in messages)
                {
                    var request = new TelegramRequest
                    {
                        chat_id = chatId,
                        text = $"<a href='{user.Url}'>{message}</a>",
                        parse_mode = "HTML"
                    };
                    var requestBody = JsonSerializer.Serialize(request, this.JsonOptions);
                    var content = new StringContent(requestBody, Encoding.UTF8, "application/json");
                    HttpResponseMessage httpResponse = await client.PostAsync(url, content);

                    if (httpResponse.IsSuccessStatusCode)
                    {
                        continue;
                    }

                    throw new Exception($"API Error sending messages to telegram: {httpResponse.StatusCode}");
                }
            }
        }
    }
}