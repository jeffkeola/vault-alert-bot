namespace Core.Models
{
    public class HyperliquidUser
    {
        public string Id { get; set; }
        public string Name { get; set; }
        public string Url => $"https://app.hyperliquid.xyz/vaults/{this.Id}";
    }
}