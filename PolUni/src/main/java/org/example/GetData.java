package org.example;

import java.net.URI;
import java.net.http.HttpClient;
import java.net.http.HttpRequest;
import java.net.http.HttpResponse;
import java.time.Duration;
import java.time.temporal.ChronoUnit;

public class GetData
{

    public static final String UNIVERSITY_TYPE_URI_STRING = "https://radon.nauka.gov.pl/opendata/polon/dictionaries/institution/universityTypes";
    public static final String INSTITUTION_TYPES = "https://radon.nauka.gov.pl/opendata/polon/dictionaries/institution/institutionKinds";
    public static final String VOIVODSHIP_URI = "https://radon.nauka.gov.pl/opendata/polon/dictionaries/shared/voivodeships";
    public static final String SCIENTIFIC_INSTITUTION_TYPES = "https://radon.nauka.gov.pl/opendata/polon/dictionaries/institution/scientificInstitutionTypes";
    public static final String UNIVERSITY_STATUSES = "https://radon.nauka.gov.pl/opendata/polon/dictionaries/institution/institutionStatuses";
    public static final String SUPERVISING_UNIVERSITIES = "https://radon.nauka.gov.pl/opendata/polon/dictionaries/shared/supervisingInstitutions";

    public static String getUniversityTypes() {
        return getUniInfo(UNIVERSITY_TYPE_URI_STRING);
    }

    public static String getInstitutionTypes() {
        return getUniInfo(INSTITUTION_TYPES);
    }

    public static String getVoivodships() {
        return getUniInfo(VOIVODSHIP_URI);
    }

    public static String getScientificInstitutionTypes() {
        return getUniInfo(SCIENTIFIC_INSTITUTION_TYPES);
    }

    public static String getUniversityStatuses() {
        return getUniInfo(UNIVERSITY_STATUSES);
    }

    public static String getSupervisingAuthorities() {
        return getUniInfo(SUPERVISING_UNIVERSITIES);
    }

    private static String getUniInfo(String uri) {
        try {
            HttpClient httpClient = HTTPClientProvider.httpClient();
            HttpRequest httpRequest = HttpRequest.newBuilder(new URI(uri))
                .GET()
                .timeout(Duration.of(10, ChronoUnit.SECONDS))
                .build();
            HttpResponse<String> httpResponse =  httpClient.send(httpRequest, HttpResponse.BodyHandlers.ofString());
            return httpResponse.body();
        } catch (Exception e) {
            throw new RuntimeException(e);
        }
    }

    private GetData() {}
}
