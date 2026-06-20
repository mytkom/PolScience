package org.example;

import java.net.http.HttpClient;

import lombok.AccessLevel;
import lombok.NoArgsConstructor;

@NoArgsConstructor(access = AccessLevel.PRIVATE)
public class HTTPClientProvider
{
    private static HttpClient httpClient;

    public static HttpClient httpClient() {
        if(httpClient == null) {
            httpClient = HttpClient.newBuilder().build();
        }
        return httpClient;
    }
}
