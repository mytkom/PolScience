package org.example;

import java.net.URI;
import java.net.http.HttpClient;
import java.net.http.HttpRequest;
import java.net.http.HttpResponse;
import java.util.Arrays;
import java.util.HashSet;
import java.util.List;
import java.util.Scanner;
import java.util.Set;

import lombok.AccessLevel;
import lombok.NoArgsConstructor;

@NoArgsConstructor(access = AccessLevel.PRIVATE)
public class Utility
{

    public static String GENERAL_UNI_INFO_API = "https://radon.nauka.gov.pl/opendata/portal-search";
    public static String INSTITUTION_SPECIFIC_API = "https://radon.nauka.gov.pl/opendata/report/execute?logRequest=true";

    public static void validateInput(final Scanner sc, final int option)
    {
        boolean notValid;
        do {
            try
            {
                String menuOption = sc.nextLine();
                if (Integer.parseInt(menuOption) != option) {
                    System.out.println("Please choose the option -> " + option);
                    notValid = true;
                } else {
                    notValid = false;
                }
            }
            catch (NumberFormatException m)
            {
                System.out.println("Please choose the option -> " + option);
                notValid = true;
            }
        } while(notValid);
    }

    public static Set<String> showChosenOptionDetails(final List<WrapperHttpResp> jsonMappedHttpResponse,
                                                       final Scanner sc,
                                                       final HttpBody httpBody,
                                                       final String option,
                                                       final String httpBodyParam,
                                                       final String msg
    )
    {
        System.out.printf(msg, option);
        int count = 1;
        Set<String> validCodes = new HashSet<>();
        for (WrapperHttpResp wrapperHttpResp : jsonMappedHttpResponse) {
            System.out.println(count + ") " + wrapperHttpResp.getNameEn() + "- " + option + " num-" + wrapperHttpResp.getCode());
            validCodes.add(wrapperHttpResp.getCode());
            count++;
        }
        final Set<String> resultChoices = validateUserChoices(sc, validCodes);
        if (!resultChoices.isEmpty()) {
            httpBody.getFilter().put(httpBodyParam, resultChoices.stream().toList());
        }
        return resultChoices;
    }


    public static Set<String> validateUserChoices(final Scanner sc, final Set<String> validCodes) {
        String option = sc.nextLine();
        while (isNotValid(option, validCodes)) {
            System.out.println("Please choose valid code");
            option = sc.nextLine();
        }
        String[] results = option.split(",");
        if (results[0].equals("None")) {
            return new HashSet<>();
        }
        return new HashSet<>(Arrays.asList(results));
    }

    public static boolean isNotValid(String option, Set<String> validCodes)
    {
        try
        {
            if (!option.equals("None")) {
                if (!option.contains(","))
                {
                    if (!validCodes.contains(option))
                    {
                        return true;
                    }
                } else {
                    String[] arr = option.split(",");
                    for (String code : arr) {
                        if (!validCodes.contains(code))
                        {
                            return true;
                        }
                    }
                }
            } else {
                return false;
            }
        }
        catch (NumberFormatException m)
        {
            return true;
        }
        return false;
    }

    public static String sentHttpRequest(final String body, final String httpApi) {
        try
        {
            final HttpClient httpClient =  HTTPClientProvider.httpClient();
            final HttpRequest httpRequest = HttpRequest.newBuilder()
                .uri(new URI(httpApi))
                .headers("content-type", "application/json", "Accept", "*/*", "Accept-Encoding", "gzip, deflate, br")
                .POST(HttpRequest.BodyPublishers.ofString(body))
                .build();

            return httpClient.send(httpRequest, HttpResponse.BodyHandlers.ofString()).body();
        }
        catch (Exception e)
        {
            throw new RuntimeException(e.getMessage());
        }
    }

}
