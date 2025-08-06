using System.Text.Json;

using Core.Models;

using Microsoft.Data.SqlClient;
using Microsoft.Extensions.Configuration;

namespace Core.Services
{
    public class HyperliquidSnapshotFilterDto
    {
        public string UserId { get; set; }
        public DateTime? MinTimestamp { get; set; }
        public DateTime? MaxTimestamp { get; set; }
    }
    public class HyperliquidSnapshotDto
    {
        public long Id { get; set; }
        public string Json { get; set; }
        public string UserId { get; set; }
        public DateTime Timestamp { get; set; }
        public DateTime CreatedUtc { get; set; }
    }

    public class HyperliquidPositionDto
    {
        public long Id { get; set; }
        public string UserId { get; set; }
        public long SnapshotId { get; set; }
        public string Coin { get; set; }
        public decimal Size { get; set; }
        public decimal Value { get; set; }
        public decimal EntryPx { get; set; }
        public DateTime CreatedUtc { get; set; }
    }

    public class HyperliquidSnapshotSummary
    {
        public long Id { get; set; }
        public string Name { get; set; }
        public string UserId { get; set; }
        public DateTime Timestamp { get; set; }
    }

    public class HyperliquidSnapshot
    {
        public long Id { get; set; }
        public string UserId { get; set; }
        public DateTime Timestamp { get; set; }
        public List<HyperliquidPosition> Positions { get; set; }
    }
    public class HyperliquidPosition
    {
        public string Coin { get; set; }
        public decimal Size { get; set; }
        public decimal Value { get; set; }
        public decimal EntryPx { get; set; }
    }

    public interface IHyperliquidDatabaseClient
    {
        Task<HyperliquidSnapshot> CreateSnapshotAsync(HyperliquidApiSnpashot response, HyperliquidUser user);
        Task<List<HyperliquidSnapshotSummary>> GetSnapshotSummariesAsync(string userId);
        Task<HyperliquidSnapshot> GetCurrentSnasphotAsync(HyperliquidUser user);
        Task<(HyperliquidSnapshot Current, HyperliquidSnapshot Previous)> GetCurrentAndPreviousSnasphotsAsync(HyperliquidUser user);

        Task<HyperliquidUser> GetUserAsync(string userId);
        Task<List<HyperliquidUser>> GetUsersAsync();
        Task<HyperliquidUser> CreateUserAsync(HyperliquidUser user);

    }

    public class HyperliquidDatabaseClient : IHyperliquidDatabaseClient
    {
        protected readonly JsonSerializerOptions JsonOptions;
        protected readonly string ConnectionString;

        public HyperliquidDatabaseClient(IConfiguration configuration)
        {
            this.JsonOptions = new JsonSerializerOptions { PropertyNamingPolicy = JsonNamingPolicy.CamelCase, WriteIndented = true };
            this.ConnectionString = configuration.GetConnectionString("CryptoStalker");
        }

        public async Task<HyperliquidUser> GetUserAsync(string userId)
        {
            const string query = "SELECT Id, Name FROM HLUser WHERE Id = @userId";

            await using var conn = new SqlConnection(this.ConnectionString);
            await conn.OpenAsync();

            await using var command = new SqlCommand(query, conn);
            command.Parameters.AddWithValue("@userId", userId);

            await using var reader = await command.ExecuteReaderAsync();
            if (await reader.ReadAsync())
            {
                var id = reader.GetString(reader.GetOrdinal("Id"));
                var name = reader.GetString(reader.GetOrdinal("Name"));

                return new HyperliquidUser
                {
                    Id = id,
                    Name = name
                };
            }
            return null; // No record found
        }
        public async Task<List<HyperliquidUser>> GetUsersAsync()
        {
            var users = new List<HyperliquidUser>();

            const string query = "SELECT Id, Name from HLUser";
            await using var conn = new SqlConnection(this.ConnectionString);
            await conn.OpenAsync();

            await using var command = new SqlCommand(query, conn);

            await using var reader = await command.ExecuteReaderAsync();
            while (await reader.ReadAsync())
            {
                users.Add(new HyperliquidUser
                {
                    Id = reader.GetString(reader.GetOrdinal("Id")),
                    Name = reader.GetString(reader.GetOrdinal("Name")),
                });
            }
            return users;
        }
        public async Task<HyperliquidUser> CreateUserAsync(HyperliquidUser user)
        {
            using var conn = new SqlConnection(this.ConnectionString);
            conn.Open();

            var command = new SqlCommand(
                "INSERT INTO HLUser (id, name) VALUES (@id, @name)",
                conn);

            command.Parameters.Clear();
            command.Parameters.AddWithValue("@id", user.Id);
            command.Parameters.AddWithValue("@name", user.Name);

            await command.ExecuteNonQueryAsync();

            return user;
        }

        public async Task<HyperliquidSnapshot> GetCurrentSnasphotAsync(HyperliquidUser user)
        {
            const string query = @"
            SELECT TOP 1 Id, UserId, Timestamp
            FROM HLSnapshot
            WHERE UserId = @userId
            ORDER BY CreatedUtc DESC";

            await using var conn = new SqlConnection(this.ConnectionString);
            await conn.OpenAsync();

            await using var command = new SqlCommand(query, conn);
            command.Parameters.AddWithValue("@userId", user.Id);

            await using var reader = await command.ExecuteReaderAsync();
            if (await reader.ReadAsync())
            {
                var snapshotId = reader.GetInt64(reader.GetOrdinal("Id"));

                var snapshot = new HyperliquidSnapshot()
                {
                    Id = snapshotId,
                    UserId = reader.GetString(reader.GetOrdinal("UserId")),
                    Timestamp = reader.GetDateTime(reader.GetOrdinal("Timestamp")),
                    Positions = await this.GetPositionsBySnapshotIdAsync(snapshotId)
                };
                return snapshot;
            }

            return null; // No record found

        }
        public async Task<(HyperliquidSnapshot Current, HyperliquidSnapshot Previous)> GetCurrentAndPreviousSnasphotsAsync(HyperliquidUser user)
        {
            const string query = @"
            SELECT TOP 2 Id, UserId, Timestamp
            FROM HLSnapshot
            WHERE UserId = @userId
            ORDER BY CreatedUtc DESC";

            await using var conn = new SqlConnection(this.ConnectionString);
            await conn.OpenAsync();

            await using var command = new SqlCommand(query, conn);
            command.Parameters.AddWithValue("@userId", user.Id);

            await using var reader = await command.ExecuteReaderAsync();
            var snapshots = new List<HyperliquidSnapshot>();
            while (await reader.ReadAsync())
            {
                var snapshotId = reader.GetInt64(reader.GetOrdinal("Id"));
                snapshots.Add(new HyperliquidSnapshot()
                {
                    Id = snapshotId,
                    UserId = reader.GetString(reader.GetOrdinal("UserId")),
                    Timestamp = reader.GetDateTime(reader.GetOrdinal("Timestamp")),
                    Positions = await this.GetPositionsBySnapshotIdAsync(snapshotId)
                });
            }

            if (snapshots.Count == 0)
            {
                return (null, null);
            }
            if (snapshots.Count == 1)
            {
                return (snapshots[0], null);
            }

            return (snapshots[0], snapshots[1]);
        }

        public async Task<HyperliquidSnapshot> CreateSnapshotAsync(HyperliquidApiSnpashot response, HyperliquidUser user)
        {
            var snapshotDto = await this.CreateSnapshotDtoAsync(response, user);
            var positions = await this.CreatePositionsAsync(response, snapshotDto);
            return new HyperliquidSnapshot
            {
                Id = snapshotDto.Id,
                Timestamp = snapshotDto.Timestamp,
                UserId = snapshotDto.UserId,
                Positions = positions.Select(p => new HyperliquidPosition
                {
                    Coin = p.Coin,
                    EntryPx = p.EntryPx,
                    Size = p.Size,
                    Value = p.Value
                }).ToList()
            };
        }

        public async Task<List<HyperliquidSnapshotSummary>> GetSnapshotSummariesAsync(string userId)
        {
            var summaries = new List<HyperliquidSnapshotSummary>();
            var query = @" Select hls.Id, hlu.Name, hls.UserId, hls.Timestamp 
                FROM HLSnapshot hls 
                JOIN HLUser hlu on hls.UserId = hlu.Id";

            if (!string.IsNullOrWhiteSpace(userId))
            {
                query += " where hls.UserId=@userId";
            }

            query += "order by CreatedUtc Desc";

            await using var conn = new SqlConnection(this.ConnectionString);
            await conn.OpenAsync();

            await using var command = new SqlCommand(query, conn);
            if (!string.IsNullOrWhiteSpace(userId))
            {
                command.Parameters.AddWithValue("userId", userId);
            }

            await using var reader = await command.ExecuteReaderAsync();
            while (await reader.ReadAsync())
            {
                summaries.Add(new HyperliquidSnapshotSummary
                {
                    Id = reader.GetInt64(reader.GetOrdinal("Id")),
                    Name = reader.GetString(reader.GetOrdinal("Name")),
                    UserId = reader.GetString(reader.GetOrdinal("UserId")),
                    Timestamp = DateTime.SpecifyKind(reader.GetDateTime(reader.GetOrdinal("Timestamp")), DateTimeKind.Utc),
                });
            }
            return summaries;
        }
        private async Task<HyperliquidSnapshotDto> CreateSnapshotDtoAsync(HyperliquidApiSnpashot response, HyperliquidUser user)
        {
            using var conn = new SqlConnection(this.ConnectionString);
            conn.Open();

            var command = new SqlCommand(
                "INSERT INTO HLSnapshot (UserId, Json, Timestamp, CreatedUtc) VALUES (@userId, @json, @timestamp, @createdUtc); Select SCOPE_IDENTITY();",
                conn);

            var snapshot = new HyperliquidSnapshotDto
            {
                Timestamp = response.Timestamp,
                CreatedUtc = DateTime.UtcNow,
                Json = JsonSerializer.Serialize(response, this.JsonOptions),
                UserId = user.Id
            };

            var dateCreatedUtc = DateTime.UtcNow;
            command.Parameters.Clear();
            command.Parameters.AddWithValue("@userId", snapshot.UserId);
            command.Parameters.AddWithValue("@json", snapshot.Json);
            command.Parameters.AddWithValue("@timestamp", snapshot.Timestamp);
            command.Parameters.AddWithValue("@createdUtc", snapshot.CreatedUtc);

            var insertedId = await command.ExecuteScalarAsync();
            snapshot.Id = Convert.ToInt64(insertedId);

            return snapshot;
        }
        private async Task<List<HyperliquidPositionDto>> CreatePositionsAsync(HyperliquidApiSnpashot response, HyperliquidSnapshotDto snapshotDto)
        {
            using var conn = new SqlConnection(this.ConnectionString);
            conn.Open();

            var values = new List<HyperliquidPositionDto>();

            foreach (var position in response.AssetPositions)
            {
                values.Add(new HyperliquidPositionDto
                {
                    CreatedUtc = DateTime.UtcNow,
                    SnapshotId = snapshotDto.Id,
                    UserId = snapshotDto.UserId,
                    Coin = position.Position.Coin,
                    EntryPx = position.Position.EntryPx,
                    Size = position.Position.Szi,
                    Value = position.Position.PositionValue
                });
            }

            foreach (var position in values)
            {
                var command = new SqlCommand(
                    "INSERT INTO HLPosition (UserId, SnapshotId, Coin, Size, PositionValue, EntryPx, CreatedUtc) VALUES (@userId, @snasphotId, @coin, @size, @positionValue, @entrypx, @createdUtc); Select SCOPE_IDENTITY();",
                    conn);

                command.Parameters.Clear();
                command.Parameters.AddWithValue("@userId", position.UserId);
                command.Parameters.AddWithValue("@snasphotId", position.SnapshotId);
                command.Parameters.AddWithValue("@coin", position.Coin);
                command.Parameters.AddWithValue("@size", position.Size);
                command.Parameters.AddWithValue("@positionValue", position.Value);
                command.Parameters.AddWithValue("@entrypx", position.EntryPx);
                command.Parameters.AddWithValue("@createdUtc", position.CreatedUtc);

                // execute
                var insertedId = await command.ExecuteScalarAsync();
                position.Id = Convert.ToInt64(insertedId);
            }

            return values;
        }
        private async Task<List<HyperliquidPosition>> GetPositionsBySnapshotIdAsync(long snapshotId)
        {
            var positions = new List<HyperliquidPosition>();

            const string query = @"
            SELECT Coin, Size, PositionValue, EntryPx
            FROM HLPosition
            WHERE SnapshotId = @snapshotId";

            await using var conn = new SqlConnection(this.ConnectionString);
            await conn.OpenAsync();

            await using var command = new SqlCommand(query, conn);
            command.Parameters.AddWithValue("@snapshotId", snapshotId);

            await using var reader = await command.ExecuteReaderAsync();
            while (await reader.ReadAsync())
            {
                positions.Add(new HyperliquidPosition
                {
                    Coin = reader.GetString(reader.GetOrdinal("Coin")),
                    Size = reader.GetDecimal(reader.GetOrdinal("Size")),
                    Value = reader.GetDecimal(reader.GetOrdinal("PositionValue")),
                    EntryPx = reader.GetDecimal(reader.GetOrdinal("EntryPx"))
                });
            }

            return positions;
        }
    }
}