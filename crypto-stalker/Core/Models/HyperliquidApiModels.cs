namespace Core.Models
{
    using System.Collections.Generic;
    using System.Text.Json;
    using System.Text.Json.Serialization;

    public class StringToDecimalConverter : JsonConverter<decimal>
    {
        public override decimal Read(ref Utf8JsonReader reader, Type typeToConvert, JsonSerializerOptions options)
        {
            if (reader.TokenType == JsonTokenType.String)
            {
                if (decimal.TryParse(reader.GetString(), out var value))
                {
                    return value;
                }
            }
            else if (reader.TokenType == JsonTokenType.Number)
            {
                return reader.GetDecimal();
            }

            throw new JsonException("Invalid value for decimal.");
        }

        public override void Write(Utf8JsonWriter writer, decimal value, JsonSerializerOptions options)
        {
            writer.WriteStringValue(value.ToString());
        }
    }

    public class HyperliquidApiSnpashot
    {
        public MarginSummary MarginSummary { get; set; }
        public MarginSummary CrossMarginSummary { get; set; }
        [JsonConverter(typeof(StringToDecimalConverter))]
        public decimal CrossMaintenanceMarginUsed { get; set; }
        [JsonConverter(typeof(StringToDecimalConverter))]
        public decimal Withdrawable { get; set; }
        public List<AssetPosition> AssetPositions { get; set; }
        public long Time { get; set; } // identifier
        public DateTime Timestamp => DateTimeOffset.FromUnixTimeMilliseconds(this.Time).UtcDateTime;
    }

    public class MarginSummary
    {
        [JsonConverter(typeof(StringToDecimalConverter))]
        public decimal AccountValue { get; set; }
        [JsonConverter(typeof(StringToDecimalConverter))]
        public decimal TotalNtlPos { get; set; }
        [JsonConverter(typeof(StringToDecimalConverter))]
        public decimal TotalRawUsd { get; set; }
        [JsonConverter(typeof(StringToDecimalConverter))]
        public decimal TotalMarginUsed { get; set; }
    }

    public class AssetPosition
    {
        public string Type { get; set; }
        public Position Position { get; set; }
    }

    public class Position
    {
        public string Coin { get; set; } // Id
        [JsonConverter(typeof(StringToDecimalConverter))]
        public decimal Szi { get; set; } // Size
        public Leverage Leverage { get; set; }
        [JsonConverter(typeof(StringToDecimalConverter))]
        public decimal EntryPx { get; set; } // Entry Price
        [JsonConverter(typeof(StringToDecimalConverter))]
        public decimal PositionValue { get; set; } // Value in USD
        [JsonConverter(typeof(StringToDecimalConverter))]
        public decimal UnrealizedPnl { get; set; }
        [JsonConverter(typeof(StringToDecimalConverter))]
        public decimal ReturnOnEquity { get; set; }
        [JsonConverter(typeof(StringToDecimalConverter))]
        public decimal? LiquidationPx { get; set; }
        [JsonConverter(typeof(StringToDecimalConverter))]
        public decimal MarginUsed { get; set; }
        [JsonConverter(typeof(StringToDecimalConverter))]
        public decimal MaxLeverage { get; set; } // actually an int
        public CumFunding CumFunding { get; set; }
        public decimal? MarkPx => this.Szi > 0 ? this.PositionValue / this.Szi : (decimal?)null;
    }

    public class Leverage
    {
        public string Type { get; set; }
        public int Value { get; set; }
    }

    public class CumFunding
    {
        [JsonConverter(typeof(StringToDecimalConverter))]
        public decimal AllTime { get; set; }
        [JsonConverter(typeof(StringToDecimalConverter))]
        public decimal SinceOpen { get; set; }
        [JsonConverter(typeof(StringToDecimalConverter))]
        public decimal SinceChange { get; set; }
    }
}