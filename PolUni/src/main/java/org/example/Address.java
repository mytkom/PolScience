package org.example;

import com.fasterxml.jackson.annotation.JsonIgnoreProperties;
import lombok.Getter;
import lombok.Setter;

@Getter
@Setter
@JsonIgnoreProperties(ignoreUnknown = true)
public class Address
{
    private String country;
    private String voivodeship;
    private String city;
    private String postalCd;
    private String street;
    private String bNumber;
    private String lNumber;
    private String dateFrom;
}
